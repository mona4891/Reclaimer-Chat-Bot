"""High-level moderation actions (kick/ban/tempban) — permission checks plus the RCON + ban-store side effects."""

import auth
import moderators
import bans
import rcon
import server_info


def do_kick(actor_name: str, actor_uid: str, target_name: str):
    target_info = server_info.get_player_info(target_name)
    target_uid = target_info.get("uid", "")

    if target_uid and auth.is_protected(target_uid):
        rcon.send_chat("I won't act against the server administrator.")
        return False
    if not auth.is_owner(actor_uid) and target_uid and moderators.is_mod(target_uid):
        rcon.send_chat(f"@{actor_name}: Moderators cannot act against other moderators.")
        return False

    rcon.send_command(f"kick {rcon.quote_if_needed(target_name)}")
    rcon.send_chat(f"{target_name} has been removed. You're welcome.")
    return True


def do_ban(actor_name: str, actor_uid: str, target_name: str):
    target_info = server_info.get_player_info(target_name)
    target_uid = target_info.get("uid", "")
    target_ip = target_info.get("ip", "")

    if target_uid and auth.is_protected(target_uid):
        rcon.send_chat("I won't act against the server administrator.")
        return False
    if not auth.is_owner(actor_uid) and target_uid and moderators.is_mod(target_uid):
        rcon.send_chat(f"@{actor_name}: Moderators cannot act against other moderators.")
        return False

    # Reclaimer's own "ban" command handles both banning and removing the
    # connected player, so there's no separate kick-and-ban pair to send
    # here the way ElDewrito needed (Server.KickBanPlayer).
    bans.add_ban(target_name, target_uid, target_ip, f"Banned by {actor_name}", moderator=actor_name)
    rcon.send_chat(f"{target_name} has been permanently banned.")
    return True


def do_tempban(actor_name: str, actor_uid: str, target_name: str, duration: int):
    target_info = server_info.get_player_info(target_name)
    target_uid = target_info.get("uid", "")
    target_ip = target_info.get("ip", "")

    if target_uid and auth.is_protected(target_uid):
        rcon.send_chat("I won't act against the server administrator.")
        return False
    if not auth.is_owner(actor_uid) and target_uid and moderators.is_mod(target_uid):
        rcon.send_chat(f"@{actor_name}: Moderators cannot act against other moderators.")
        return False

    bans.add_ban(target_name, target_uid, target_ip, f"Temp banned by {actor_name}", duration, moderator=actor_name)
    rcon.send_chat(f"{target_name} has been banned for {duration} minutes.")
    return True
