"""
Ban handling for Project Reclaimer.

Unlike ElDewrito, Reclaimer bans are handled natively by the dedicated
server itself: "ban"/"banip"/"unban"/"bans" RCON commands manage a ban
list shared across every server pointed at the same list (per the
project's hosting docs), with built-in support for durations ("30m",
"12h", "7d", "2w", or none for permanent) and IP/CIDR ranges. So unlike
cortana_bot's original bans.py, this module does NOT keep its own
bans.json as the source of truth — the server's own list is authoritative
and this is a thin wrapper around the real "ban"/"unban"/"bans" commands,
plus a local text log purely for a human-readable audit trail.

One important asymmetry from Reclaimer's own `help ban`/`help unban`:
  ban <player | player ID | IP | range> [time] [reason]   -- accepts a
    connected player's NAME, since the server can resolve it live.
  unban <player ID | IP | range>                          -- name is NOT
    accepted, only an ID/IP/range, since the person being unbanned isn't
    connected for the server to resolve a name against.
So remove_ban() below needs the actual ID or IP that was recorded when
the ban was made, not just a display name — see get_active_bans().

The exact shape of the "bans" command's reply data hasn't been confirmed
against a real ban yet (the test server had none when this was built) —
get_active_bans() parses it defensively and falls back to showing
whatever it can, but if the dashboard's ban list looks off once there
are real entries, paste the raw `bans` RCON reply back and the parsing
below can be corrected to match.
"""

from datetime import datetime

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


def add_ban(name: str, uid: str = "", ip: str = "", reason: str = "Banned", duration_minutes: int = None, moderator: str = "AutoMod") -> bool:
    """Bans by NAME (the server resolves it live since the player is
    still connected at ban time) — uid/ip are accepted for call-site
    compatibility with the old ElDewrito-shaped callers but aren't
    needed for the command itself."""
    duration_str = _format_duration(duration_minutes)
    parts = ["ban", rcon.quote_if_needed(name)]
    if duration_str:
        parts.append(duration_str)
    if reason:
        parts.append(reason)
    command = " ".join(parts)

    result = rcon.send_command(command)
    ok = result is not None
    log_ban_action("BAN", name, moderator, reason, duration_str or "permanent")
    if not ok:
        logger.info(f"[BAN] Command failed: {command!r}")
    return ok


def remove_ban(identifier: str, moderator: str = "Unknown") -> bool:
    """identifier must be the player ID or IP/range that was actually
    banned (see module docstring) — a display name will not work here,
    unlike add_ban()."""
    result = rcon.send_command(f"unban {rcon.quote_if_needed(identifier)}")
    ok = result is not None
    log_ban_action("UNBAN", identifier, moderator, "Unbanned", "N/A")
    return ok


def get_active_bans() -> list:
    """Returns whatever the server's own "bans" command reports. Parsed
    defensively since the reply shape hasn't been confirmed against a
    real ban entry yet -- see module docstring."""
    data = rcon.send_command("bans")
    if data is None:
        return []

    # Try the most likely shapes: a "bans" key holding a list, or the
    # data itself already being that list.
    raw_list = data.get("bans") if isinstance(data, dict) else None
    if raw_list is None and isinstance(data, list):
        raw_list = data
    if raw_list is None:
        return []

    active = []
    for entry in raw_list:
        if isinstance(entry, dict):
            active.append({
                "name": entry.get("name") or entry.get("player") or entry.get("id", "?"),
                "uid": entry.get("id") or entry.get("player_id") or entry.get("uid", ""),
                "ip": entry.get("ip") or entry.get("address", ""),
                "reason": entry.get("reason", ""),
                "banned_at": entry.get("banned_at") or entry.get("created", ""),
                "expires_at": entry.get("expires_at") or entry.get("expires"),
                "permanent": entry.get("permanent", not entry.get("expires_at") and not entry.get("expires")),
                "moderator": entry.get("moderator", ""),
            })
        else:
            # A bare string entry (e.g. just an ID or IP) -- show it as-is
            # rather than dropping it silently.
            active.append({
                "name": str(entry), "uid": str(entry), "ip": "", "reason": "",
                "banned_at": "", "expires_at": None, "permanent": True, "moderator": "",
            })
    return active


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
