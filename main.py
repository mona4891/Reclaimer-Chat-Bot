"""
Cortana Bot — entry point (Project Reclaimer edition).

Loads config, connects RCON, starts every background thread (Discord
bridge, moderation, announcements, the web dashboard...), and then hands
off to the chat watcher, which registers itself as the live chat-event
handler and blocks forever — Reclaimer pushes chat over the same RCON
socket rather than needing a log file tailed (see chat_watcher.py and
rcon.py's module docstrings).

Run with: python main.py
"""

import sys
import threading
import time

import config
import state
from logger_setup import logger

import rcon
import moderators
import player_stats
import permanent_memory
import ai_providers
import discord_bridge
import background_tasks
import web_dashboard
import chat_watcher


def main():
    cfg = config.load_config()
    state.apply_config(cfg)

    providers_loaded = [n for n, _, has_key in ai_providers.CLOUD_PROVIDER_CHAIN if has_key()]
    mods = moderators.load_mods()
    memory_lines = len(permanent_memory.load_memory().splitlines()) if permanent_memory.load_memory() else 0
    stats_count = len(player_stats.load_stats())

    discord_configured = bool(state.DISCORD_WEBHOOK_URL or state.DISCORD_BOT_TOKEN)

    if not ai_providers.is_ollama_running():
        logger.info("WARNING: Ollama not running or model not pulled. Local model disabled.")

    logger.info("=" * 55)
    logger.info(f"  {config.BOT_NAME} AI Bot — Project Reclaimer edition")
    logger.info(f"  Owner ID:     {state.OWNER_UUID}")
    logger.info(f"  PrivKey:      {'set' if state.OWNER_PRIVKEY else 'NOT SET'}")
    logger.info(f"  Providers:    {' -> '.join(p.capitalize() for p in providers_loaded) if providers_loaded else 'None!'}")
    logger.info(f"  Mods:         {len(mods)} loaded")
    logger.info(f"  Memory:       {memory_lines} entries")
    logger.info(f"  Stats:        {stats_count} players tracked")
    logger.info(f"  Announcements:{len(config.ANNOUNCEMENTS)} configured")
    logger.info(f"  Discord:      {'configured' if discord_configured else 'not configured'} (off by default)")
    logger.info(f"  AFK:          off | timeout: {config.AFK_TIMEOUT_MINUTES}min")
    logger.info("  AutoMod:      off by default")
    logger.info(f"  Local:        off | {config.OLLAMA_MODEL}")
    logger.info(f"  Config:       {config.CONFIG_FILE}")
    logger.info(f"  RCON:         {config.RCON_HOST}:{state.RCON_PORT}")
    logger.info("=" * 55)
    logger.info(f"  {config.BOT_NAME} AI Bot — Ready!")
    logger.info("=" * 55)

    if not state.RCON_PASSWORD:
        logger.info("ERROR: RCON_PASSWORD not set in config.txt")
        sys.exit(1)
    if not state.OWNER_UUID:
        logger.info("ERROR: OWNER_UUID not set in config.txt (your Reclaimer player ID)")
        sys.exit(1)
    if not state.OWNER_PRIVKEY:
        logger.info("WARNING: OWNER_PRIVKEY not set — admin commands disabled!")
    if not providers_loaded:
        logger.info("ERROR: No API keys loaded!")
        sys.exit(1)
    if not rcon.connect_rcon():
        logger.info("[ERROR] Could not connect to RCON.")
        sys.exit(1)

    if discord_configured:
        discord_bridge.start_discord_bot()

    # Background threads. No check_banned_players() here — Reclaimer
    # enforces its own ban list server-side, so there's nothing to sweep
    # for (see background_tasks.py's module docstring).
    threading.Thread(target=rcon.reconnect_rcon, daemon=True).start()
    threading.Thread(target=background_tasks.check_killstreaks, daemon=True).start()
    threading.Thread(target=background_tasks.check_first_blood, daemon=True).start()
    threading.Thread(target=background_tasks.check_game_state, daemon=True).start()
    threading.Thread(target=background_tasks.check_players, daemon=True).start()
    threading.Thread(target=background_tasks.check_afk, daemon=True).start()
    threading.Thread(target=background_tasks.check_callouts, daemon=True).start()
    threading.Thread(target=background_tasks.scheduled_announcements, daemon=True).start()
    threading.Thread(target=web_dashboard.start_web_server, daemon=True).start()
    threading.Thread(target=background_tasks.scheduled_backup, daemon=True).start()

    time.sleep(1)
    rcon.send_chat(f"{config.BOT_NAME} online. Type !cortana <question> or just mention my name.")
    chat_watcher.watch_chat()


if __name__ == "__main__":
    main()
