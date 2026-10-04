"""
RCON connection to a Project Reclaimer dedicated server.

Project Reclaimer's own protocol isn't publicly documented (the project is
early development with private source), so everything here was reverse
engineered against a real running 0.8.11 test server rather than taken
from any spec:

  - Connect: a plain WebSocket to ws://host:port/ (no special path needed).
  - Auth: the FIRST message on the connection must be exactly
        {"type": "auth", "password": "<password>"}
    A wrong-shaped first message gets a graceful JSON error reply; a
    second wrong-shaped message on the same connection gets the socket
    closed outright, so connect_rcon() only ever sends the auth message
    once and in the right shape.
  - Commands: {"type": "command", "command": "<full command text, e.g.
    'players' or 'kick Sirius spamming'>"} -> a reply on the SAME socket,
    either {"type":"reply","ok":true,"id":...,"text":"...","data":{...}}
    or {"type":"error","text":"..."}. Bad JSON or an unknown command
    replies with an error rather than closing the connection.
  - Events arrive unprompted on the same socket, interleaved with command
    replies: {"type":"event","event":"chat","channel":"all","id":"<player
    id>","name":"<name>","text":"<message>","time":<unix>} for a real
    player chat message (confirmed against actual in-game chat, not just
    the bot's own "say" broadcasts). Newer server builds also push a
    {"type":"event","event":"kill",...} for every death; its exact fields
    haven't been confirmed yet, so handlers receive the whole event dict
    (see set_event_handler()) rather than pre-split arguments.

Because replies and events share one socket, this module runs a single
background reader thread that pulls every incoming message and either
resolves a pending command (matched by the "id" we assign when sending)
or hands an event off to whatever chat handler has been registered —
see set_chat_handler(). Everything else in the bot calls the blocking,
thread-safe send_command()/send_chat() functions below same as it always
has; the reader thread and the request/reply bookkeeping are invisible
to callers.

IMPORTANT: handlers must never run ON the reader thread. A handler that
calls send_command()/send_chat() blocks waiting for a reply that only the
reader thread can deliver -- so running it there freezes all RCON traffic
until the 8s timeout (every other thread's commands time out too, then
the backlog arrives all at once). Chat events therefore get a thread each,
and other events (e.g. "kill") go through one in-order worker queue each.
"""

import itertools
import json
import queue
import threading
import time

from websocket import create_connection, WebSocketConnectionClosedException

import config
import state
from logger_setup import logger
from tts import speak_to_game

ws = None
ws_lock = threading.Lock()
ws_connected = False

_reader_thread = None
_request_id = itertools.count(1)
_pending = {}          # request id -> {"event": threading.Event, "reply": dict or None}
_pending_lock = threading.Lock()

_chat_handler = None   # set by chat_watcher.set_chat_handler()
_event_handlers = {}   # event name -> handler(event_dict), see set_event_handler()
_event_queues = {}     # event name -> queue feeding that event's worker thread
_timed_out = set()     # ids of commands that timed out, so a late reply isn't logged as a mystery


def set_chat_handler(handler):
    """Register the function called for every incoming chat event, as
    handler(player_name, player_id, message). Replaces chat_watcher.py's
    old job of tailing a log file -- Reclaimer pushes chat live on this
    same socket, so there's nothing to tail."""
    global _chat_handler
    _chat_handler = handler


def set_event_handler(event_name: str, handler):
    """Register handler(event_dict) for any other pushed event type, e.g.
    set_event_handler("kill", fn). The handler gets the raw decoded JSON
    message so callers can read whichever fields the server actually
    sends. Chat keeps its own split-argument handler above. Events of
    one type are handled in order on their own worker thread (never on
    the reader thread -- see the module docstring)."""
    _event_handlers[event_name] = handler
    if event_name not in _event_queues:
        q = queue.Queue()
        _event_queues[event_name] = q
        threading.Thread(target=_event_worker, args=(event_name, q), daemon=True).start()


def _event_worker(event_name: str, q):
    while True:
        msg = q.get()
        handler = _event_handlers.get(event_name)
        if not handler:
            continue
        try:
            handler(msg)
        except Exception as e:
            logger.error(f"[RCON] {event_name} handler raised: {e}")


def _run_chat_handler(name, player_id, text):
    handler = _chat_handler
    if not handler:
        return
    try:
        handler(name, player_id, text)
    except Exception as e:
        logger.error(f"[RCON] Chat handler raised: {e}")


def _reader_loop(my_ws):
    """Runs on its own daemon thread for the lifetime of one connection.
    Reads every incoming message and either resolves a pending
    send_command() call or dispatches a chat event. Exits (and flips
    ws_connected off) the moment the socket errors or closes, which is
    what tells reconnect_rcon() to reconnect."""
    global ws_connected
    while True:
        try:
            raw = my_ws.recv()
        except (WebSocketConnectionClosedException, OSError, Exception) as e:
            if my_ws is ws:
                logger.info(f"[RCON] Reader thread stopping (connection lost): {e}")
                ws_connected = False
            else:
                # An old socket that connect_rcon() replaced and closed --
                # the live connection is fine, don't flag it as down.
                logger.info("[RCON] Old connection's reader thread stopped.")
            return
        if my_ws is not ws:
            # Replaced by a newer connection: stop reading so chat events
            # aren't delivered twice (once per live socket).
            try:
                my_ws.close()
            except Exception:
                pass
            return
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            logger.info(f"[RCON] Non-JSON message ignored: {raw!r}")
            continue

        msg_type = msg.get("type")

        if msg_type == "event":
            event_name = msg.get("event")
            if event_name == "chat":
                if _chat_handler:
                    threading.Thread(
                        target=_run_chat_handler,
                        args=(msg.get("name", ""), msg.get("id", ""), msg.get("text", "")),
                        daemon=True,
                    ).start()
            else:
                q = _event_queues.get(event_name)
                if q is not None:
                    q.put(msg)
            continue

        if msg_type in ("reply", "error"):
            req_id = msg.get("id")
            with _pending_lock:
                entry = _pending.get(req_id)
                if entry is None and req_id is None and len(_pending) == 1:
                    # Some replies come back with "id":null. If exactly
                    # one command is waiting, it can only be that one's.
                    entry = next(iter(_pending.values()))
            if entry is not None:
                entry["reply"] = msg
                entry["event"].set()
            elif req_id in _timed_out:
                _timed_out.discard(req_id)
                logger.info(f"[RCON] Late reply to timed-out command (id={req_id})")
            else:
                logger.info(f"[RCON] Unmatched {msg_type} (id={req_id!r}): {str(msg)[:300]}")
            continue


def connect_rcon() -> bool:
    global ws, ws_connected, _reader_thread
    logger.info(f"[RCON] Connecting to ws://{config.RCON_HOST}:{state.RCON_PORT}/ ...")
    try:
        new_ws = create_connection(
            f"ws://{config.RCON_HOST}:{state.RCON_PORT}/",
            timeout=10
        )
        new_ws.send(json.dumps({"type": "auth", "password": state.RCON_PASSWORD}))
        new_ws.settimeout(10)
        auth_reply = json.loads(new_ws.recv())
        if not auth_reply.get("ok"):
            logger.error(f"[RCON] Auth rejected: {auth_reply}")
            new_ws.close()
            ws_connected = False
            return False

        new_ws.settimeout(None)  # reader thread blocks on recv() indefinitely
        with ws_lock:
            old_ws = ws
            ws = new_ws
        ws_connected = True
        if old_ws is not None:
            # Never leave the previous socket open: its reader thread would
            # keep delivering every chat event a second time.
            try:
                old_ws.close()
            except Exception:
                pass
        server_name = auth_reply.get("server", "?")
        version = auth_reply.get("version", "?")
        logger.info(f"[RCON] Connected and authenticated to '{server_name}' (server v{version}).")

        _reader_thread = threading.Thread(target=_reader_loop, args=(new_ws,), daemon=True)
        _reader_thread.start()
        return True
    except Exception as e:
        ws_connected = False
        logger.error(f"[RCON] Connection failed: {e}")
        return False


def reconnect_rcon():
    while True:
        time.sleep(15)
        if not ws_connected:
            logger.info("[RCON] Attempting reconnect...")
            if connect_rcon():
                send_chat(f"{config.BOT_NAME} reconnected.")


def quote_if_needed(value: str) -> str:
    """Reclaimer's help text says to quote a player name if it has spaces
    in it ("quote names with spaces") when it's an argument inside a
    larger command string. A name/value with no spaces is passed through
    bare."""
    if " " in value and not (value.startswith('"') and value.endswith('"')):
        return f'"{value}"'
    return value


def send_command_full(command: str, timeout: float = 8.0, keep_errors: bool = False) -> dict:
    """Like send_command(), but returns the WHOLE successful reply
    ({"ok":..., "text":..., "data":{...}}) instead of just its "data",
    or None on failure/timeout/error reply. Needed by commands whose
    useful output may be in "text" (e.g. maps/modes lists, or a
    confirmation line to relay back to chat). With keep_errors=True an
    error reply ({"type":"error","text":...} or ok:false) is returned
    as-is instead of None, so the caller can show the server's reason;
    None then only means "no connection / send failed / timed out"."""
    global ws_connected
    if not ws_connected or ws is None:
        return None

    # Keep join passwords out of the log file.
    shown = "password ***" if command.lower().startswith("password") else command

    req_id = next(_request_id)
    entry = {"event": threading.Event(), "reply": None}
    with _pending_lock:
        _pending[req_id] = entry

    try:
        payload = json.dumps({"type": "command", "command": command, "id": req_id})
        with ws_lock:
            ws.send(payload)
    except Exception as e:
        logger.info(f"[RCON] Send failed: {e}")
        ws_connected = False
        with _pending_lock:
            _pending.pop(req_id, None)
        return None

    got_reply = entry["event"].wait(timeout)
    with _pending_lock:
        _pending.pop(req_id, None)

    if not got_reply:
        logger.info(f"[RCON] No reply to command within {timeout}s: {shown!r}")
        _timed_out.add(req_id)
        if len(_timed_out) > 500:
            _timed_out.clear()
        return None

    reply = entry["reply"]
    if reply.get("type") == "error":
        logger.info(f"[RCON] Command error for {shown!r}: {reply.get('text')}")
        return reply if keep_errors else None
    if not reply.get("ok", True):
        logger.info(f"[RCON] Command not ok for {shown!r}: {reply.get('text')}")
        return reply if keep_errors else None
    return reply


def send_command(command: str, timeout: float = 8.0) -> dict:
    """Send a command and block for its reply, e.g. send_command("players")
    or send_command('kick "Some Player" spamming'). Returns the reply's
    "data" dict on success (which may be {} for commands with no data
    payload, e.g. "say"), or None on failure/timeout/error reply -- check
    for None specifically, since {} is a valid successful-but-empty
    result."""
    reply = send_command_full(command, timeout)
    if reply is None:
        return None
    return reply.get("data", {})


def send_rcon(command: str) -> bool:
    """Fire-and-forget version of send_command() for call sites that don't
    need the reply -- kept under the old name so the rest of the codebase
    (background threads issuing kicks, etc.) didn't all need renaming.
    Still waits for SOME reply (to keep request ids from piling up
    unanswered) but discards it and reports only whether the send itself
    went out."""
    if not ws_connected or ws is None:
        return False
    result = send_command(command)
    return result is not None


def send_chat(message: str):
    """Broadcast a message as Cortana via the "say" command. Reclaimer's
    own server already prefixes broadcasts with "[Server]", so this adds
    the bot's own name after that rather than duplicating ElDewrito's
    separate BOT_PREFIX-in-Server.Say pattern."""
    words = message.split()
    chunk, lines = [], []
    for word in words:
        if len(" ".join(chunk + [word])) > config.CHAT_LINE_LIMIT:
            lines.append(" ".join(chunk))
            chunk = [word]
        else:
            chunk.append(word)
    if chunk:
        lines.append(" ".join(chunk))

    for line in lines:
        full_line = f"{config.BOT_PREFIX} {line}"
        try:
            ok = send_command(f"say {full_line}")
            if ok is None:
                # Don't flip ws_connected here: None also means a timeout
                # or an error reply on a perfectly healthy socket, and
                # flagging it made reconnect_rcon() open a second socket.
                # A genuinely dead socket is flagged by the reader thread
                # and by send_command_full's send exception.
                logger.info(f"[BOT] Send failed for: {full_line}")
            else:
                logger.info(f"[BOT] {full_line}")
                if state.voice_enabled:
                    speak_to_game(line)  # Speak the message without the prefix
        except Exception as e:
            logger.info(f"[BOT] Send failed: {e}")
        time.sleep(0.4)


def is_connected() -> bool:
    return ws_connected
