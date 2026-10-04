"""Match-end summary: announces results in chat, updates stats, saves match history, posts to Discord."""

import json
import os
from datetime import datetime

import requests

import config
import state
import rcon
import player_stats


def save_match(match_data: dict):
    history = []
    if os.path.exists(config.MATCH_LOG_FILE):
        try:
            with open(config.MATCH_LOG_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            pass
    history.append(match_data)
    history = history[-100:]
    with open(config.MATCH_LOG_FILE, "w") as f:
        json.dump(history, f, indent=2)


def process_match_end(info: dict):
    """Called when a match ends. Generates summary, saves stats, logs match."""
    players = info.get("players", [])
    map_name = info.get("map", "unknown")
    mode = info.get("variant", "unknown")

    if not players:
        return

    winner = max(players, key=lambda p: p.get("score", 0))
    most_kills = max(players, key=lambda p: p.get("kills", 0))
    most_deaths = max(players, key=lambda p: p.get("deaths", 0))

    w_name = winner.get("name", "?")
    w_score = winner.get("score", 0)
    k_name = most_kills.get("name", "?")
    k_kills = most_kills.get("kills", 0)
    d_name = most_deaths.get("name", "?")
    d_deaths = most_deaths.get("deaths", 0)

    parts = [f"Match over on {map_name} ({mode})."]
    if w_score > 0:
        parts.append(f"{w_name} wins with {w_score} points.")
    if k_name != w_name and k_kills > 0:
        parts.append(f"Most kills: {k_name} ({k_kills}).")
    if d_deaths > 0 and len(players) > 1:
        parts.append(f"Most deaths: {d_name} ({d_deaths}) — better luck next time.")

    rcon.send_chat(" ".join(parts))

    # Update persistent stats
    if state.stats_enabled:
        winner_uid = winner.get("uid", "")
        for p in players:
            name = p.get("name", "")
            uid = p.get("uid", "")
            kills = p.get("kills", 0)
            deaths = p.get("deaths", 0)
            score = p.get("score", 0)
            won = 1 if uid == winner_uid and w_score > 0 else 0
            player_stats.update_player_stats(name, uid, kills, deaths, score, won)

    # Save match to history
    match_data = {
        "map": map_name, "mode": mode, "winner": w_name,
        "players": [{"name": p.get("name"), "score": p.get("score", 0),
                     "kills": p.get("kills", 0), "deaths": p.get("deaths", 0)} for p in players],
        "played_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_match(match_data)

    # Post to Discord
    if state.discord_enabled and state.DISCORD_WEBHOOK_URL:
        discord_summary = f"**Match ended** — {map_name} ({mode})\n"
        discord_summary += f"🏆 Winner: **{w_name}** ({w_score} pts)\n"
        for p in sorted(players, key=lambda x: x.get("score", 0), reverse=True):
            discord_summary += f"• {p.get('name','?')} — K:{p.get('kills',0)} D:{p.get('deaths',0)} Score:{p.get('score',0)}\n"
        try:
            requests.post(state.DISCORD_WEBHOOK_URL, json={"username": "Cortana", "content": discord_summary}, timeout=5)
        except Exception:
            pass
