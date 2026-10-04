"""Warning system: tracks per-player warning counts/history and logs them to disk."""

import json
import os
from datetime import datetime

import config


def load_warnings() -> dict:
    if not os.path.exists(config.WARNINGS_FILE):
        return {}
    try:
        with open(config.WARNINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_warnings(w: dict):
    with open(config.WARNINGS_FILE, "w") as f:
        json.dump(w, f, indent=2)


def log_warning_action(player_name: str, player_uid: str, moderator: str, reason: str, warning_count: int):
    """Log warning actions to a text file."""
    from logger_setup import logger
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(config.WARNING_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] WARNING #{warning_count} | Player: {player_name} (UID: {player_uid}) | Mod: {moderator} | Reason: {reason}\n")
    except Exception as e:
        logger.info(f"[LOG] Failed to write warning log: {e}")


def add_warning(player_name: str, player_uid: str, reason: str, moderator: str = "AutoMod") -> int:
    warnings = load_warnings()
    key = player_uid or player_name.lower()
    if key not in warnings:
        warnings[key] = {"name": player_name, "uid": player_uid, "count": 0, "history": []}
    warnings[key]["count"] += 1
    warnings[key]["name"] = player_name
    warnings[key]["history"].append({"reason": reason, "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "moderator": moderator})
    save_warnings(warnings)

    log_warning_action(player_name, player_uid, moderator, reason, warnings[key]["count"])

    return warnings[key]["count"]


def get_warnings(player_name: str, player_uid: str) -> dict:
    warnings = load_warnings()
    key = player_uid or player_name.lower()
    return warnings.get(key, {"name": player_name, "uid": player_uid, "count": 0, "history": []})


def clear_warnings(player_name: str) -> bool:
    warnings = load_warnings()
    key_to_remove = None
    for key, data in warnings.items():
        if data.get("name", "").lower() == player_name.lower():
            key_to_remove = key
            break
    if key_to_remove:
        del warnings[key_to_remove]
        save_warnings(warnings)
        return True
    return False
