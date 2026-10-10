"""
Ban handling for Project Reclaimer.

Unlike ElDewrito, Reclaimer bans are handled natively by the dedicated
server itself: "ban"/"banip"/"unban"/"bans" RCON commands manage a ban
list shared across every server pointed at the same list, with built-in
support for durations ("90s", "30m", "12h", "7d", "2w", or none for
permanent) and IP/CIDR ranges. So this module does NOT keep its own
bans.json as the source of truth -- the server's own list is
authoritative and this is a thin wrapper around the real commands, plus a
local text log purely for a human-readable audit trail.

From RCON.md:
  ban <player | player ID | IP | range> [time] [reason]
      a connected player's NAME, or an ID/IP/range for someone who is not
      connected. A connected player it matches leaves at once. Banning a
      connected player records their ID, IP and (when available) device
      fingerprint together as one linked action.
  unban <name | player ID | device fingerprint | IP | range>
      lifts the whole matching action, including its linked entries. A
      name only works when exactly one active ban has it; otherwise the
      server refuses and says so (use the exact ID/IP from `bans`).
  bans -> data {players, ips, devices}, each entry with id or ip, name,
      reason, banned_by, banned_at, group (when linked) and expires (when
      timed). get_active_bans() merges entries that share a `group` into
      one row, since unbanning any one of them lifts all of them.
"""

import ipaddress
import re
import time
from datetime import datetime, timezone

import config
import rcon
from logger_setup import logger


def log_ban_action(action: str, identifier: str, moderator: str, reason: str, duration: str = "permanent"):
    """Local human-readable audit trail only -- NOT the source of truth
    for what's actually banned (the server's own list is)."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(config.BAN_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {action} | Target: {identifier} | Mod: {moderator} | Duration: {duration} | Reason: {reason}\n")
    except Exception as e:
        logger.warning(f"[BAN] Failed to write ban log: {e}")


def _format_duration(duration_minutes) -> str:
    """Reclaimer's ban command takes a duration like 30m/12h/7d/2w, or no
    time argument at all for a permanent ban. cortana_bot's callers pass
    minutes (matching the old ElDewrito-style tempban UX), so convert."""
    if not duration_minutes:
        return ""
    minutes = int(duration_minutes)
    if minutes % (60 * 24 * 7) == 0 and minutes >= 60 * 24 * 7:
        return f"{minutes // (60 * 24 * 7)}w"
    if minutes % (60 * 24) == 0 and minutes >= 60 * 24:
        return f"{minutes // (60 * 24)}d"
    if minutes % 60 == 0 and minutes >= 60:
        return f"{minutes // 60}h"
    return f"{minutes}m"


DURATION_RE = re.compile(r"^\d+[smhdw]$", re.IGNORECASE)


def is_duration(token: str) -> bool:
    """A time as the server takes it: a number and a unit (90s, 30m, 12h, 7d, 2w)."""
    return bool(DURATION_RE.match(token or ""))


def looks_like_ban_target(token: str) -> bool:
    """True for a player ID (64 hex characters), an IP address or a range --
    the targets `ban` accepts for someone who isn't connected."""
    token = (token or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", token):
        return True
    try:
        ipaddress.ip_network(token, strict=False)
        return True
    except ValueError:
        return False


def _result(reply) -> tuple:
    """(ok, text) from a send_command_full(keep_errors=True) reply."""
    if reply is None:
        return False, "No reply from the server (it may not be connected)."
    text = (reply.get("text") or "").strip()
    if reply.get("type") == "error" or not reply.get("ok", True):
        return False, text or "The server rejected the command."
    return True, text


def ban_target(target: str, duration: str = "", reason: str = "", moderator: str = "AutoMod") -> tuple:
    """Run `ban <target> [time] [reason]`. `target` is a connected player's
    name or an ID/IP/range; `duration` is a server time like "7d" (empty =
    permanent). Returns (ok, server text)."""
    parts = ["ban", rcon.quote_if_needed(target)]
    if duration:
        parts.append(duration)
    if reason:
        parts.append(reason)
    ok, text = _result(rcon.send_command_full(" ".join(parts), keep_errors=True))
    log_ban_action("BAN" if ok else "BAN-FAILED", target, moderator, reason, duration or "permanent")
    if not ok:
        logger.info(f"[BAN] Command failed for {target!r}: {text}")
    return ok, text


def add_ban(name: str, uid: str = "", ip: str = "", reason: str = "Banned", duration_minutes: int = None, moderator: str = "AutoMod") -> bool:
    """Bans by NAME (the server resolves it live since the player is
    still connected at ban time) -- uid/ip are accepted for call-site
    compatibility with the old ElDewrito-shaped callers but aren't
    needed for the command itself."""
    ok, _ = ban_target(name, _format_duration(duration_minutes), reason, moderator)
    return ok


def remove_ban_full(identifier: str, moderator: str = "Unknown") -> tuple:
    """`unban` by name, player ID, device fingerprint, IP or range.
    Returns (ok, server text) -- the text says why when the server refuses
    (for instance, several bans share that name)."""
    ok, text = _result(rcon.send_command_full(f"unban {rcon.quote_if_needed(identifier)}", keep_errors=True))
    log_ban_action("UNBAN" if ok else "UNBAN-FAILED", identifier, moderator, "Unbanned", "N/A")
    return ok, text


def remove_ban(identifier: str, moderator: str = "Unknown") -> bool:
    return remove_ban_full(identifier, moderator)[0]


def _stamp(value):
    """Unix seconds -> "YYYY-MM-DD HH:MM UTC"; anything else as text."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value) if value else ""
    if n > 1e9:
        return datetime.fromtimestamp(n, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _expiry(value):
    """(expires_unix_or_None, seconds_left_or_None, text). `expires` is a
    Unix time for a timed ban and absent/0 for a permanent one; a small
    number is taken as seconds remaining instead."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None, None, "permanent"
    if n <= 0:
        return None, None, "permanent"
    if n > 1e9:
        left = max(0, int(n - time.time()))
        return int(n), left, _left_text(left)
    left = int(n)
    return int(time.time()) + left, left, _left_text(left)


def _left_text(seconds: int) -> str:
    if seconds <= 0:
        return "expiring"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    return (" ".join(parts) or f"{seconds}s") + " left"


def get_active_bans() -> list:
    """The server's own ban list as one row per ban action. `bans` returns
    {players, ips, devices}; entries recorded together share a `group` and
    are merged here (unbanning any one lifts all of them). Each row:
    name, uid (player ID), ip, device, identifier (best thing to pass to
    unban), reason, banned_at, expires (unix or None), expires_in (seconds
    or None), expires_at (text), permanent, moderator, linked (entries)."""
    data = rcon.send_command("bans")
    if data is None:
        return []

    if isinstance(data, list):
        groups_in = [("players", data)]
    else:
        groups_in = [(kind, data.get(kind) or []) for kind in ("players", "ips", "devices")]
        if not any(items for _, items in groups_in) and isinstance(data.get("bans"), list):
            groups_in = [("players", data["bans"])]   # older shape

    rows, by_group = [], {}
    for kind, items in groups_in:
        for entry in items:
            if not isinstance(entry, dict):
                entry = {"id" if kind != "ips" else "ip": str(entry)}
            key = entry.get("group")
            row = by_group.get(key) if key else None
            if row is None:
                row = {"name": "", "uid": "", "ip": "", "device": "", "reason": "", "banned_at": "",
                       "expires": None, "expires_in": None, "expires_at": "permanent", "permanent": True,
                       "moderator": "", "linked": 0}
                rows.append(row)
                if key:
                    by_group[key] = row
            row["linked"] += 1

            if kind == "players":
                row["uid"] = row["uid"] or entry.get("id") or entry.get("player_id") or ""
            elif kind == "ips":
                row["ip"] = row["ip"] or entry.get("ip") or entry.get("address") or ""
            else:
                row["device"] = row["device"] or entry.get("id") or entry.get("device") or entry.get("fingerprint") or ""
            if kind == "players" or not row["name"]:
                row["name"] = entry.get("name") or row["name"]
            row["reason"] = row["reason"] or entry.get("reason", "")
            row["moderator"] = row["moderator"] or entry.get("banned_by") or entry.get("moderator", "")
            row["banned_at"] = row["banned_at"] or _stamp(entry.get("banned_at") or entry.get("created"))

            expires, left, text = _expiry(entry.get("expires") if "expires" in entry else entry.get("expires_at"))
            if expires is not None and (row["expires"] is None or expires > row["expires"]):
                row["expires"], row["expires_in"], row["expires_at"], row["permanent"] = expires, left, text, False

    for row in rows:
        row["identifier"] = row["uid"] or row["device"] or row["ip"] or row["name"]
        if not row["name"]:
            row["name"] = row["identifier"] or "?"
    return rows


def is_banned(uid: str = None, name: str = None, ip: str = None) -> dict:
    """Kept for call-site compatibility (automod.py, background sweeps),
    but since Reclaimer enforces bans natively server-side, nothing in
    this bot needs to poll for and re-kick an already-banned player the
    way the ElDewrito version did — the server won't let them connect
    or stay connected in the first place. This just checks the server's
    own list for informational purposes."""
    for ban in get_active_bans():
        if uid and ban.get("uid") == uid:
            return ban
        if name and ban.get("name", "").lower() == (name or "").lower():
            return ban
        if ip and ban.get("ip") == ip:
            return ban
    return {}
