"""
Game-control chat commands for Project Reclaimer, backed by the RCON
commands the dev added: map/mode/load/nextmap (+ maps/modes listings),
teamcount/shuffle, startvote/passvote/cancelvote, and the owner-only
servername/password.

Syntax note: Reclaimer's exact argument syntax for these commands isn't
documented, so arguments are passed through to the server exactly as the
moderator typed them (`!ai map <args>` -> RCON `map <args>`). Use
`!ai maps` / `!ai modes` to see the names the server accepts, and quote
names with spaces the way Reclaimer's own `help` says to. The server's
reply (or its error text) is relayed back to chat so a typo is obvious.

What each does, per the dev's notes:
  map / mode / load   end the current game and start the chosen map and
                      mode in the next lobby
  nextmap             sets the next game WITHOUT ending this one
  servername/password rename the server / set or clear its join password
                      until the server restarts
  teamcount/shuffle   spread players over teams
  startvote           end round, end game, shuffle, kick, playlist ballot
  passvote/cancelvote resolve the running vote

Permissions: everything here is moderator+ except servername and
password, which are owner-only (dispatched from commands_admin.py).

Output goes through a `say(text)` callable that defaults to in-game chat.
The web dashboard passes its own collector instead (see web_dashboard.py's
/api/game), so the same code serves both and the dashboard can show each
result inline. handle()/handle_admin() return True on success and False
when the command failed or was refused, so callers can tell.
"""

import config
import auth
import moderators
import rcon
import server_info
from logger_setup import logger


def _no_reply() -> str:
    if not rcon.is_connected():
        return "Not connected to the server right now — command not sent."
    return "No reply from the server in time — it may still have worked, check the game."


def _clip(text: str) -> str:
    """Trim to the chat budget so a long reply doesn't spam the lobby."""
    text = " ".join(str(text).split())
    if len(text) > config.CHAT_TOTAL_LIMIT:
        text = text[:config.CHAT_TOTAL_LIMIT - 3].rstrip() + "..."
    return text


def _names_from_reply(reply: dict, key: str) -> list:
    """Pull a list of names out of a maps/modes reply. The payload shape
    isn't documented, so this accepts a list of strings, a list of dicts
    (name/id/title/label), either under data[key] or as any list inside
    data -- and falls back to splitting the reply's text."""
    data = reply.get("data")
    items = None
    if isinstance(data, dict):
        items = data.get(key)
        if not isinstance(items, list):
            items = next((v for v in data.values() if isinstance(v, list)), None)
    elif isinstance(data, list):
        items = data

    names = []
    for it in items or []:
        if isinstance(it, str):
            names.append(it)
        elif isinstance(it, dict):
            for k in ("name", "id", "title", "label"):
                if it.get(k):
                    names.append(str(it[k]))
                    break

    if not names:
        text = reply.get("text") or ""
        for chunk in text.replace(",", "\n").splitlines():
            chunk = chunk.strip().lstrip("-*• ").strip()
            if chunk:
                names.append(chunk)
    return names


def list_names(command: str, key: str):
    """Ask the server for its maps/modes. Returns (names, error): `names`
    is a list (possibly empty) or None on failure, with `error` holding a
    short reason. Used by the chat listing below and the dashboard's
    dropdowns."""
    reply = rcon.send_command_full(command, keep_errors=True)
    if reply is None:
        return None, _no_reply()
    if reply.get("type") == "error" or not reply.get("ok", True):
        return None, f"{command.capitalize()} failed: {_clip(reply.get('text') or 'unknown error')}"
    return _names_from_reply(reply, key), None


def _send_listing(label: str, command: str, key: str, say) -> bool:
    names, error = list_names(command, key)
    if names is None:
        say(error)
        return False
    if not names:
        say(f"No {label} reported.")
        return False

    shown, used = [], 0
    for n in names:
        if used + len(n) + 2 > config.CHAT_TOTAL_LIMIT - 30:
            break
        shown.append(n)
        used += len(n) + 2
    line = f"{label.capitalize()} ({len(names)}): {', '.join(shown)}"
    if len(shown) < len(names):
        line += f" (+{len(names) - len(shown)} more)"
    say(line)
    return True


def _run(player_name: str, command: str, success: str, say, show_server_text: bool = True) -> bool:
    """Send one RCON command and report the outcome through `say`.
    `success` is the line used when the server confirms without any text
    of its own."""
    reply = rcon.send_command_full(command, keep_errors=True)
    if reply is None:
        say(_no_reply())
        return False
    if reply.get("type") == "error" or not reply.get("ok", True):
        say(f"Server rejected that: {_clip(reply.get('text') or 'unknown error')}")
        return False
    shown = "password ***" if command.lower().startswith("password") else command
    logger.info(f"[GAME] {player_name} ran RCON: {shown}")
    text = (reply.get("text") or "").strip() if show_server_text else ""
    say(_clip(text) if text else success)
    return True


def handle(player_name: str, player_uid: str, cmd: str, args: list, say=None) -> bool:
    """Dispatch one of config.GAME_CMDS. Caller (commands_mod.handle, or
    the dashboard's /api/game) has already checked permission."""
    say = say or rcon.send_chat
    rest = " ".join(args)

    if cmd == "maps":
        return _send_listing("maps", "maps", "maps", say)

    if cmd == "modes":
        return _send_listing("modes", "modes", "modes", say)

    if cmd in ("map", "mode", "load"):
        if not args:
            say(f"Usage: !ai {cmd} <name> — ends the current game. See !ai maps / !ai modes.")
            return False
        return _run(player_name, f"{cmd} {rest}", f"Switching to {rest} — it starts in the next lobby.", say)

    if cmd == "nextmap":
        if not args:
            say("Usage: !ai nextmap <name> — sets the next game without ending this one.")
            return False
        return _run(player_name, f"nextmap {rest}", f"Next map set to {rest}.", say)

    if cmd == "teamcount":
        if len(args) != 1 or not args[0].isdigit() or int(args[0]) < 1:
            say("Usage: !ai teamcount <number>")
            return False
        return _run(player_name, f"teamcount {args[0]}", f"Team count set to {args[0]}.", say)

    if cmd == "shuffle":
        return _run(player_name, "shuffle", "Teams shuffled.", say)

    if cmd == "startvote":
        if not args:
            say("Usage: !ai startvote <endround|endgame|shuffle|kick <player>|playlist>")
            return False
        vote_args = list(args)
        if vote_args[0].lower() == "kick":
            # A vote-kick is still a kick: apply the same protections as !ai kick.
            if len(vote_args) < 2:
                say("Usage: !ai startvote kick <player>")
                return False
            target_name, _ = server_info.get_target_name(vote_args[1:])
            target_uid = server_info.get_player_info(target_name).get("uid", "")
            if target_uid and auth.is_protected(target_uid):
                say("I won't act against the server administrator.")
                return False
            if not auth.is_owner(player_uid) and target_uid and moderators.is_mod(target_uid):
                say(f"@{player_name}: Moderators cannot act against other moderators.")
                return False
            vote_args = ["kick", rcon.quote_if_needed(target_name)]
        return _run(player_name, f"startvote {' '.join(vote_args)}", "Vote started.", say)

    if cmd == "passvote":
        return _run(player_name, "passvote", "Vote passed.", say)

    if cmd == "cancelvote":
        return _run(player_name, "cancelvote", "Vote cancelled.", say)

    return False


def handle_admin(player_name: str, player_uid: str, cmd: str, args: list, say=None) -> bool:
    """servername / password. Caller (commands_admin.handle, or the
    dashboard's /api/game) has already checked the player is the owner."""
    say = say or rcon.send_chat

    if cmd == "servername":
        if not args:
            say("Usage: !ai servername <new name> (lasts until the server restarts)")
            return False
        name = " ".join(args)
        return _run(player_name, f"servername {name}", f"Server renamed to {name}.", say, show_server_text=False)

    if cmd == "password":
        if not args:
            say("Usage: !ai password <new password> | !ai password clear")
            return False
        value = " ".join(args)
        # Never echo the password (or the server's reply, which may contain
        # it) back to chat or the dashboard.
        if value.lower() in ("clear", "off", "none"):
            return _run(player_name, config.PASSWORD_CLEAR_COMMAND, "Join password cleared.", say, show_server_text=False)
        return _run(player_name, f"password {value}", "Join password updated.", say, show_server_text=False)

    return False
