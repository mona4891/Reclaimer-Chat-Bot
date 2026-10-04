"""Persistent per-player match stats (kills/deaths/score/wins)."""

import json
import os
from datetime import datetime

import config


def load_stats() -> dict:
    if not os.path.exists(config.STATS_FILE):
        return {}
    try:
        with open(config.STATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_stats(stats: dict):
    with open(config.STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def update_player_stats(player_name: str, player_uid: str, kills: int, deaths: int, score: int, wins: int = 0):
    stats = load_stats()
    key = player_uid or player_name.lower()
    if key not in stats:
        stats[key] = {
            "name": player_name, "uid": player_uid,
            "kills": 0, "deaths": 0, "score": 0,
            "wins": 0, "matches": 0, "first_seen": datetime.now().strftime("%Y-%m-%d")
        }
    stats[key]["name"] = player_name
    stats[key]["kills"] += kills
    stats[key]["deaths"] += deaths
    stats[key]["score"] += score
    stats[key]["wins"] += wins
    stats[key]["matches"] += 1
    stats[key]["last_seen"] = datetime.now().strftime("%Y-%m-%d")
    save_stats(stats)


def get_player_stats(player_name: str, player_uid: str = "") -> dict:
    stats = load_stats()
    # Search by UID first, then by name
    if player_uid:
        key = player_uid
        if key in stats:
            return stats[key]
    for key, data in stats.items():
        if data.get("name", "").lower() == player_name.lower():
            return data
    return {}


def format_stats(data: dict) -> str:
    if not data:
        return "No stats found."
    name = data.get("name", "?")
    kills = data.get("kills", 0)
    deaths = data.get("deaths", 0)
    score = data.get("score", 0)
    wins = data.get("wins", 0)
    matches = data.get("matches", 0)
    kd = round(kills / deaths, 2) if deaths > 0 else kills
    return (f"{name} — K:{kills} D:{deaths} KD:{kd} "
            f"Score:{score} Wins:{wins} Matches:{matches}")
