"""Permanent memory notes: freeform server notes players add with `!ai remember`."""

import os
from datetime import datetime

import config


def load_memory() -> str:
    if not os.path.exists(config.MEMORY_FILE):
        return ""
    try:
        with open(config.MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def append_memory(player_name: str, entry: str):
    existing = load_memory()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = (existing + f"\n[{now}] {player_name}: {entry}").strip()
    with open(config.MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(updated)


def clear_memory():
    with open(config.MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("")
