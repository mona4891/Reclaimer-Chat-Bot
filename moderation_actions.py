"""High-level moderation actions (kick/ban/tempban/mute/unban) -- permission
checks plus the RCON side effects.

Every action reports through `say` (in-game chat by default; the dashboard
passes a collector) and returns True only if the server accepted it. The
server's own error text is relayed on failure, so "No player is named
'Brav'" reaches the moderator instead of a false "has been removed".

Who is credited ("Bravo was kicked by Alice.", and the server's audit log)
is set by the caller with `rcon.acting_as(name)`; anything without one is
attributed to the bot.
"""

import auth
import moderators
import bans
import rcon
import server_info


def _blocked(actor_name, actor_uid, target_uid, say, verb="act against") -> bool:
    """True (after saying why) if the target is the server owner, or a
    moderator and the actor isn't the owner."""
    if target_uid and auth.is_protected(target_uid):
        say("I won't act against the server administrator.")
        return True
    if not auth.is_owner(actor_uid) and target_uid and moderators.is_mod(target_uid):
        say(f"@{actor_name}: Moderators cannot {verb} other moderators.")
        return True
    return False


def _send(command: str):
    """(ok, server text) for one moderation command."""
    return bans._result(rcon.send_command_full(command, keep_errors=True))


def do_kick(actor_name: str, actor_uid: str, target_name: str, reason: str = "", say=None) -> bool:
    say = say or rcon.send_chat
    target_uid = server_info.get_player_info(target_name).get("uid", "")
    if _blocked(actor_name, actor_uid, target_uid, say):
        return False

    ok, text = _send(" ".join(filter(None, ["kick", rcon.quote_if_needed(target_name), reason])))
    if not ok:
        say(f"Couldn't kick {target_name}: {text}")
        return False
    say(f"{target_name} has been removed. You're welcome.")
    return True


def do_ban(actor_name: str, actor_uid: str, target: str, reason: str = "", duration: str = "", say=None) -> bool:
    """`target` is a connected player's name, or -- for someone who isn't
    connected -- a player ID, IP address or range. `duration` is a server
    time such as "7d"; empty means permanent."""
    say = say or rcon.send_chat
    if bans.looks_like_ban_target(target):
        # An explicit ID still gets the owner/moderator protections.
        if _blocked(actor_name, actor_uid, target if len(target) == 64 else "", say):
            return False
    else:
        target_uid = server_info.get_player_info(target).get("uid", "")
        if _blocked(actor_name, actor_uid, target_uid, say):
            return False

    ok, text = bans.ban_target(target, duration, reason or f"Banned by {actor_name}", moderator=actor_name)
    if not ok:
        say(f"Couldn't ban {target}: {text}")
        return False
    say(f"{target} has been banned for {duration}." if duration else f"{target} has been permanently banned.")
    return True


def do_tempban(actor_name: str, actor_uid: str, target_name: str, duration, reason: str = "", say=None) -> bool:
    """`duration` is minutes (int, as the dashboard sends) or a server time
    string like "90s" / "12h" / "7d"."""
    duration_str = duration if isinstance(duration, str) and bans.is_duration(duration) else bans._format_duration(duration)
    if not duration_str:
        duration_str = "5m"
    return do_ban(actor_name, actor_uid, target_name,
                  reason=reason or f"Temp banned by {actor_name}", duration=duration_str, say=say)


def do_mute(actor_name: str, actor_uid: str, target_name: str, duration: str = "", reason: str = "", say=None) -> bool:
    """Nobody hears the player's text or voice. Lasts for `duration` (a
    server time), until unmute, or until the server restarts."""
    say = say or rcon.send_chat
    target_uid = server_info.get_player_info(target_name).get("uid", "")
    if target_uid and auth.is_protected(target_uid):
        say("I won't act against the server administrator.")
        return False

    parts = ["mute", rcon.quote_if_needed(target_name)]
    if duration:
        parts.append(duration)
    if reason:
        parts.append(reason)
    ok, text = _send(" ".join(parts))
    if not ok:
        say(f"Couldn't mute {target_name}: {text}")
        return False
    say(f"{target_name} has been muted" + (f" for {duration}." if duration else "."))
    return True


def do_unmute(actor_name: str, actor_uid: str, target_name: str, say=None) -> bool:
    say = say or rcon.send_chat
    ok, text = _send(f"unmute {rcon.quote_if_needed(target_name)}")
    if not ok:
        say(f"Couldn't unmute {target_name}: {text}")
        return False
    say(f"{target_name} has been unmuted.")
    return True


def do_unban(actor_name: str, identifier: str, say=None) -> bool:
    """By name, player ID, device fingerprint, IP or range. Lifts the whole
    matching action, including its linked entries."""
    say = say or rcon.send_chat
    ok, text = bans.remove_ban_full(identifier, moderator=actor_name)
    if not ok:
        say(f"Couldn't unban '{identifier}': {text}")
        return False
    say(f"Unbanned {identifier}.")
    return True
