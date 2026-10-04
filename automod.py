"""
Auto-moderation: detects slurs, excessive caps and spam in chat, and
escalates through the warn -> kick -> tempban ladder.
"""

import re
import threading
import time

import config
import state
import rcon
import auth
import moderators
import warnings_store
import bans
import server_info

spam_tracker = {}
spam_lock = threading.Lock()
compiled_slurs = [re.compile(p, re.IGNORECASE) for p in config.SLUR_PATTERNS]


def check_slurs(message: str) -> bool:
    return any(p.search(message) for p in compiled_slurs)


def check_excessive_caps(message: str) -> bool:
    if len(message) < config.CAPS_MIN_LENGTH:
        return False
    letters = [c for c in message if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= config.CAPS_THRESHOLD


def check_spam(player_name: str, message: str) -> bool:
    now = time.time()
    with spam_lock:
        if player_name not in spam_tracker:
            spam_tracker[player_name] = []
        spam_tracker[player_name] = [(t, m) for t, m in spam_tracker[player_name] if now - t <= config.SPAM_WINDOW]
        spam_tracker[player_name].append((now, message.lower()))
        return sum(1 for _, m in spam_tracker[player_name] if m == message.lower()) >= config.SPAM_THRESHOLD


def automod_check(player_name: str, player_uid: str, player_ip: str, message: str):
    if not state.automod_enabled:
        return
    if auth.is_owner(player_uid) or moderators.is_mod(player_uid):
        return
    violation = None
    if check_slurs(message):
        violation = "use of prohibited language"
    elif check_excessive_caps(message):
        violation = "excessive caps"
    elif check_spam(player_name, message):
        violation = "spam"
    if violation:
        _apply_warning(player_name, player_uid, player_ip, f"AutoMod: {violation}")


def _apply_warning(player_name: str, player_uid: str, player_ip: str, reason: str):
    count = warnings_store.add_warning(player_name, player_uid, reason, moderator="AutoMod")
    remaining = max(0, config.WARN_KICK_THRESHOLD - count)
    if count < config.WARN_KICK_THRESHOLD:
        rcon.send_chat(f"@{player_name}: Warning {count}/{config.WARN_KICK_THRESHOLD} — {reason}. {remaining} left before action.")
    elif count == config.WARN_KICK_THRESHOLD:
        rcon.send_chat(f"{player_name} has been kicked after {count} warnings.")
        rcon.send_command(f"kick {rcon.quote_if_needed(player_name)}")
        warnings_store.add_warning(player_name, player_uid, "Kicked after warning threshold")
    else:
        target_info = server_info.get_player_info(player_name)
        target_ip = target_info.get("ip", player_ip)
        # Reclaimer's "ban" command removes the connected player itself,
        # so there's no separate kick command needed alongside it here.
        bans.add_ban(player_name, player_uid, target_ip, "Temp banned: repeated violations", config.WARN_TEMPBAN_DURATION)
        rcon.send_chat(f"{player_name} has been temporarily banned for {config.WARN_TEMPBAN_DURATION} minutes.")
