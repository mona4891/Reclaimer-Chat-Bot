"""
Chat commands that don't fit the admin/mod tiers cleanly: the debug dump,
config reload, memory/voice/local toggles, mod list, and raw game status.
"""

import config
import state
import rcon
import moderators
import permanent_memory
import server_info
import ai_providers
import player_stats
from logger_setup import logger


def cmd_debugall(player_name: str, player_uid: str, owner: bool):
    if not owner:
        rcon.send_chat(f"@{player_name}: Debug command restricted to owner.")
        return
    rcon.send_chat(f"[DEBUG] Bot: {config.BOT_NAME}")
    rcon.send_chat(f"[DEBUG] RCON: {'Connected' if rcon.is_connected() else 'Disconnected'}")
    rcon.send_chat(f"[DEBUG] Owner: {owner}")
    rcon.send_chat(f"[DEBUG] Bot Enabled: {state.bot_enabled}")
    rcon.send_chat(f"[DEBUG] Voice Enabled: {state.voice_enabled}")
    rcon.send_chat(f"[DEBUG] Local Enabled: {state.local_enabled}")
    info = server_info.get_server_info()
    rcon.send_chat(f"[DEBUG] Game Status: {info.get('status', 'unknown')}")
    rcon.send_chat(f"[DEBUG] Map: {info.get('map', 'unknown')}")
    rcon.send_chat(f"[DEBUG] Players: {info.get('numPlayers', 0)}/{info.get('maxPlayers', 0)}")
    providers = [n for n, _, h in ai_providers.CLOUD_PROVIDER_CHAIN if h()]
    rcon.send_chat(f"[DEBUG] AI Providers: {', '.join(p.capitalize() for p in providers) if providers else 'None'}")
    rcon.send_chat(f"[DEBUG] Ollama: {'Running' if ai_providers.is_ollama_running() else 'Not running'}")
    rcon.send_chat("[DEBUG] === End Debug ===")


def cmd_reload(player_name: str, mod_or_owner: bool):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    try:
        logger.info(f"Reloading configuration by {player_name}")
        new_config = config.load_config()
        state.apply_config(new_config)
        logger.info("Configuration reloaded successfully")
        rcon.send_chat("Configuration reloaded successfully. Changes applied.")
    except Exception as e:
        logger.error(f"Failed to reload config: {e}")
        rcon.send_chat(f"Failed to reload config: {e}")


def cmd_forget(player_name: str, mod_or_owner: bool):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    permanent_memory.clear_memory()
    rcon.send_chat("Permanent memory cleared.")


def cmd_memory(player_name: str, mod_or_owner: bool, args: list):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    if args[0].lower() == "on":
        state.memory_enabled = True
        rcon.send_chat("Memory enabled.")
    elif args[0].lower() == "off":
        state.memory_enabled = False
        rcon.send_chat("Memory disabled.")
    else:
        rcon.send_chat("Usage: !ai memory on/off")


def cmd_voice(player_name: str, mod_or_owner: bool, args: list):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    if args[0].lower() == "on":
        state.voice_enabled = True
        rcon.send_chat("Voice responses enabled.")
    elif args[0].lower() == "off":
        state.voice_enabled = False
        rcon.send_chat("Voice responses disabled.")
    else:
        rcon.send_chat("Usage: !ai voice on/off")


def cmd_local(player_name: str, mod_or_owner: bool, args: list):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    if args[0].lower() == "on":
        if ai_providers.is_ollama_running():
            state.local_enabled = True
            rcon.send_chat(f"Local model enabled ({config.OLLAMA_MODEL}).")
        else:
            rcon.send_chat(f"Ollama not running. Pull model: ollama pull {config.OLLAMA_MODEL}")
    else:
        state.local_enabled = False
        rcon.send_chat("Local model disabled.")


def cmd_modlist(player_name: str, mod_or_owner: bool):
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return
    mods = moderators.load_mods()
    if not mods:
        rcon.send_chat("No moderators assigned.")
    else:
        rcon.send_chat(f"Moderators: {', '.join(m.get('name','?') for m in mods)}")


def cmd_gamestatus():
    info = server_info.get_server_info()
    status = info.get("status", "unknown")
    server_name = info.get("server_name", "")
    phase = info.get("phase", "")

    line = f"Game status: '{status}'"
    if server_name:
        line += f" | Server: {server_name}"
    if phase:
        line += f" | Phase: {phase}"
    if info.get("votes_enabled") is not None:
        line += f" | Voting: {'on' if info.get('votes_enabled') else 'off'}"

    rcon.send_chat(line)


def cmd_mystats(player_name: str, player_uid: str):
    """Anyone's own persistent stats — self-service, no permission check.
    (Looking up ANOTHER player's stats is the separate "!ai stats <name>"
    command, which stays mod-only in commands_mod.py.)

    Beyond the persistent stats this tacks on the current live score if
    they're in a match right now, plus alive state and health/shields
    when the server reports them.
    """
    data = player_stats.get_player_stats(player_name, player_uid)
    line = f"@{player_name}: {player_stats.format_stats(data)}"

    live = server_info.get_player_info(player_name)
    if live:
        line += f" | Live: {live.get('kills', 0)}K/{live.get('deaths', 0)}D, score {live.get('score', 0)}"
        if live.get("isAlive") is True and "health" in live:
            line += f", health {server_info.fmt_pct(live.get('health'))}"
            if "shields" in live:
                line += f"/shields {server_info.fmt_pct(live.get('shields'))}"
        elif live.get("isAlive") is False:
            line += ", currently dead"

    rcon.send_chat(line)
