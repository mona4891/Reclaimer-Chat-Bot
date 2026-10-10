"""
Game-control chat commands for Project Reclaimer, backed by the RCON
commands documented in RCON.md ("Game, server and vote control"):

  maps / modes        list installed maps and modes (JSON `entries` rows:
                      name, reference, kind -- the REFERENCE is what the
                      other commands take)
  map <map>           load a map, keeping the current game rules
  mode <mode>         load a mode or saved game variant, keeping the map
  load <map> <mode>   load both
  nextmap [<map> [<mode>]]   query, or replace, the one-shot next game
                      (an omitted mode keeps the current rules); does NOT
                      end the current game
  teamcount [2-8]     query occupied teams / queue a redistribution
  shuffle             queue a balanced shuffle
  team <player> <team>  move a player (red, blue, green, orange, purple,
                      gold, brown, pink)
  endround / endgame  end the round / the game with scores as they stand
  vote                vote state and tallies, plus the playlist ballot
  startvote <endround|endgame|shuffle|kick <player>|playlist>
  passvote / cancelvote
  maxping [<ms>|off]  query / set the highest ping allowed to JOIN
  vpn [IP]            VPN-blocking status, or whether an address is refused

Owner only (dispatched from commands_admin.py):
  servername [<name>] query / rename the server live
  password [<value>]  query whether a join password is set / set it
                      ("password clear" sends `password ""`)
  vpnallow <player|player ID|IP|range> [note]   let someone join through
                      a VPN on every server sharing the ban list
  vpnrevoke <player ID|IP|range>                take that back

Map/mode/load end the current game and apply in the next ready lobby; the
server's reply is acceptance, not completion -- a `control` event follows
when the lobby has changed or says why it couldn't (chat_watcher relays
failures). Name/password/ping changes last until the server restarts.

Arguments are passed through exactly as typed, so quote references with
spaces (`!ai map "High Ground"`). Everything is moderator+ unless noted.

Output goes through a `say(text)` callable that defaults to in-game chat.
The web dashboard passes its own collector instead (see web_dashboard.py's
/api/game), so the same code serves both and the dashboard can show each
result inline. handle()/handle_admin() return True on success and False
when the command failed or was refused, so callers can tell.
"""

import re

import config
import auth
import moderators
import rcon
import server_info
from logger_setup import logger

TEAMS = ("red", "blue", "green", "orange", "purple", "gold", "brown", "pink")
VOTE_TYPES = ("endround", "endgame", "shuffle", "kick", "playlist")


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


def _entries_from_reply(reply: dict, key: str) -> list:
    """maps/modes rows as [{"name", "reference", "kind"}]. The documented
    shape is data.entries; older shapes (a list under `key`, any list in
    data, bare strings, or just the reply text) still work."""
    data = reply.get("data")
    items = None
    if isinstance(data, dict):
        items = data.get("entries")
        if not isinstance(items, list):
            items = data.get(key)
        if not isinstance(items, list):
            items = next((v for v in data.values() if isinstance(v, list)), None)
    elif isinstance(data, list):
        items = data

    entries = []
    for it in items or []:
        if isinstance(it, str):
            entries.append({"name": it, "reference": it, "kind": ""})
        elif isinstance(it, dict):
            name = next((str(it[k]) for k in ("name", "title", "label", "id") if it.get(k)), "")
            reference = str(it.get("reference") or name)
            if reference:
                entries.append({"name": name or reference, "reference": reference, "kind": str(it.get("kind") or "")})

    if not entries:
        text = reply.get("text") or ""
        for chunk in text.replace(",", "\n").splitlines():
            chunk = chunk.strip().lstrip("-*• ").strip()
            if chunk:
                entries.append({"name": chunk, "reference": chunk, "kind": ""})
    return entries


def list_entries(command: str, key: str):
    """Ask the server for its maps/modes. Returns (entries, error): a list
    of {"name", "reference", "kind"} dicts (possibly empty), or None with a
    short reason in `error`. Used by the chat listing and the dashboard."""
    reply = rcon.send_command_full(command, keep_errors=True)
    if reply is None:
        return None, _no_reply()
    if reply.get("type") == "error" or not reply.get("ok", True):
        return None, f"{command.capitalize()} failed: {_clip(reply.get('text') or 'unknown error')}"
    return _entries_from_reply(reply, key), None


def list_names(command: str, key: str):
    """Like list_entries() but just the references (what you type)."""
    entries, error = list_entries(command, key)
    if entries is None:
        return None, error
    return [e["reference"] for e in entries], None


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
        item = rcon.quote_if_needed(n)
        if used + len(item) + 2 > config.CHAT_TOTAL_LIMIT - 30:
            break
        shown.append(item)
        used += len(item) + 2
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

    if cmd in ("map", "mode"):
        if not args:
            say(f"Usage: !ai {cmd} <name> — ends the current game. See !ai {cmd}s.")
            return False
        return _run(player_name, f"{cmd} {rest}", f"Switching to {rest} — it starts in the next lobby.", say)

    if cmd == "load":
        # Chat splits on spaces, so count references the way the server
        # will: a quoted "High Ground" is ONE reference.
        if len(re.findall(r'"[^"]*"|\S+', rest)) < 2:
            say('Usage: !ai load <map> <mode> — quote names with spaces. Ends the current game.')
            return False
        return _run(player_name, f"load {rest}", f"Loading {rest} — it starts in the next lobby.", say)

    if cmd == "nextmap":
        # No arguments = query the one-shot override (and active rotation).
        return _run(player_name, f"nextmap {rest}".strip(),
                    f"Next game set to {rest}." if args else "No next-game override is set.", say)

    if cmd == "teamcount":
        if not args:
            return _run(player_name, "teamcount", "Team count queried.", say)
        if len(args) != 1 or not args[0].isdigit() or not 2 <= int(args[0]) <= 8:
            say("Usage: !ai teamcount [2-8]")
            return False
        return _run(player_name, f"teamcount {args[0]}", f"Team count set to {args[0]}.", say)

    if cmd == "shuffle":
        return _run(player_name, "shuffle", "Teams shuffled.", say)

    if cmd == "team":
        if len(args) < 2 or args[-1].lower() not in TEAMS:
            say(f"Usage: !ai team <player> <{'|'.join(TEAMS)}>")
            return False
        target = " ".join(args[:-1])
        return _run(player_name, f"team {rcon.quote_if_needed(target)} {args[-1].lower()}",
                    f"Moving {target} to {args[-1].lower()}.", say)

    if cmd == "endround":
        return _run(player_name, "endround", "Round ended.", say)

    if cmd == "endgame":
        return _run(player_name, "endgame", "Game ended.", say)

    if cmd == "vote":
        return _run(player_name, "vote", "No vote is running.", say)

    if cmd == "startvote":
        if not args or args[0].lower() not in VOTE_TYPES:
            say("Usage: !ai startvote <endround|endgame|shuffle|kick <player>|playlist>")
            return False
        vote_args = [args[0].lower()] + list(args[1:])
        if vote_args[0] == "kick":
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

    if cmd == "maxping":
        if not args:
            return _run(player_name, "maxping", "Max ping queried.", say)
        value = args[0].lower()
        if len(args) != 1 or not (value == "off" or (value.isdigit() and int(value) <= 1000)):
            say("Usage: !ai maxping [<milliseconds up to 1000>|off] — only checked as players join.")
            return False
        return _run(player_name, f"maxping {value}", f"Max ping set to {value}.", say)

    if cmd == "vpn":
        return _run(player_name, f"vpn {rest}".strip(), "VPN status queried.", say)

    return False


def handle_admin(player_name: str, player_uid: str, cmd: str, args: list, say=None) -> bool:
    """servername / password / vpnallow / vpnrevoke. Caller
    (commands_admin.handle, or the dashboard's /api/game) has already
    checked the player is the owner."""
    say = say or rcon.send_chat

    if cmd == "servername":
        if not args:
            return _run(player_name, "servername", "Server name queried.", say)
        name = " ".join(args)
        return _run(player_name, f"servername {name}", f"Server renamed to {name}.", say, show_server_text=False)

    if cmd == "password":
        if not args:
            # The server only says whether a join password is required; it
            # never returns the password itself.
            return _run(player_name, "password", "Join password queried.", say)
        value = " ".join(args)
        # Never echo the password (or the server's reply, which may contain
        # it) back to chat or the dashboard.
        if value.lower() in ("clear", "off", "none"):
            return _run(player_name, config.PASSWORD_CLEAR_COMMAND, "Join password cleared.", say, show_server_text=False)
        return _run(player_name, f"password {value}", "Join password updated.", say, show_server_text=False)

    if cmd == "vpnallow":
        if not args:
            say("Usage: !ai vpnallow <player|player ID|IP|range> [note] — for someone refused as a VPN, use the ID from the refused line.")
            return False
        return _run(player_name, f"vpnallow {' '.join(args)}", "VPN allowance added.", say)

    if cmd == "vpnrevoke":
        if len(args) != 1:
            say("Usage: !ai vpnrevoke <player ID|IP|range> — written exactly as it was allowed.")
            return False
        return _run(player_name, f"vpnrevoke {args[0]}", "VPN allowance revoked.", say)

    return False
