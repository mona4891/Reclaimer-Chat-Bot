"""Moderator role storage (mods.json) — who besides the owner can run mod commands."""

import json
import os
from datetime import datetime

import config


def load_mods() -> list:
    if not os.path.exists(config.MODS_FILE):
        return []
    try:
        with open(config.MODS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_mods(mods: list):
    with open(config.MODS_FILE, "w") as f:
        json.dump(mods, f, indent=2)


def add_mod(name: str, uid: str):
    mods = load_mods()
    mods = [m for m in mods if m.get("uid") != uid and m.get("name", "").lower() != name.lower()]
    mods.append({"name": name, "uid": uid, "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    save_mods(mods)


def remove_mod(identifier: str) -> bool:
    """Remove a moderator by name or UID."""
    mods = load_mods()
    identifier_lower = identifier.lower().replace("0x", "")

    new_mods = []
    found = False
    for m in mods:
        if m.get("name", "").lower() == identifier_lower:
            found = True
            continue
        if m.get("uid", "").lower().replace("0x", "") == identifier_lower:
            found = True
            continue
        new_mods.append(m)

    if found:
        save_mods(new_mods)
        return True
    return False


def is_mod(player_uid: str) -> bool:
    clean = player_uid.lower().replace("0x", "")
    return any(m.get("uid", "").lower().replace("0x", "") == clean for m in load_mods())
