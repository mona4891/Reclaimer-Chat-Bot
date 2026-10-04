"""
Chat handling for Project Reclaimer.

Unlike ElDewrito, there's no log file to tail here -- Reclaimer's RCON
socket pushes real player chat messages live as {"type":"event","event":
"chat",...} (see rcon.py's module docstring for how that was confirmed).
This module registers itself as rcon.py's chat handler and, for each
message, does exactly what the old log-tailing version did: decide
whether it's a command (!ai ...), a direct question (!cortana / mentions
"cortana"), or just chat to log for context / forward to Discord / feed
through auto-mod.
"""

import json
import threading
import time

import config
import state
import rcon
import auth
import command_router
import discord_bridge
import automod
import permanent_memory
import ai_queue
import server_info
from logger_setup import logger


def _on_chat_event(player_name: str, player_id: str, message: str):
    message = (message or "").strip()
    if not message:
        return

    if message.startswith(config.BOT_PREFIX):
        return
    if not (player_name or "").strip() and not (player_id or "").strip():
        # Server-generated line (e.g. "Teams have been shuffled and
        # balanced."), not a player: log it, but don't run it through
        # auto-mod, the AI trigger check, chat context or Discord.
        logger.info(f"[SERVER] {message}")
        return
    if player_name.lower() in config.IGNORED_SENDER_NAMES and not auth.is_owner(player_id):
        return
    if player_name.lower() in {"cortana", "ai"} and not auth.is_owner(player_id):
        return

    # "!ai password <secret>" carries a join password: route the real
    # command below, but keep the secret out of the log file, the AI's
    # chat context (which is sent to third-party providers) and the
    # Discord bridge. It is still visible to players in the in-game chat.
    safe_message = message
    if message.lower().startswith("!ai password"):
        safe_message = "!ai password [redacted]"

    logger.info(f"[CHAT] {player_name} ({player_id}): {safe_message}")
    state.chat_memory.append((player_name, safe_message))

    # Forward to Discord
    if state.discord_enabled and not safe_message.startswith("[Discord]"):
        threading.Thread(target=discord_bridge.send_to_discord, args=(player_name, safe_message), daemon=True).start()

    # Update AFK tracker on chat
    if player_name in state.afk_tracker:
        state.afk_tracker[player_name]["last_active"] = time.time()

    threading.Thread(target=automod.automod_check, args=(player_name, player_id, "", safe_message), daemon=True).start()

    lower = message.lower()

    if lower.startswith("!ai "):
        remainder = message[4:].strip()
        rem_parts = remainder.split()
        if not rem_parts:
            return
        first_word = rem_parts[0].lower()

        if first_word in config.ADMIN_ONLY_CMDS or first_word in config.MOD_CMDS:
            command_router.handle_command(player_name, player_id, "", remainder)
            return

        if first_word == "remember":
            entry = " ".join(rem_parts[1:])
            if entry:
                permanent_memory.append_memory(player_name, entry)
                rcon.send_chat(f"@{player_name}: Noted.")
            else:
                rcon.send_chat(f"@{player_name}: Remember what? Try: !ai remember <text>")
            return

        if not state.bot_enabled:
            rcon.send_chat(f"@{player_name}: I'm currently offline.")
            return
        ai_queue.try_queue_request(player_name, player_id, remainder)
        return

    triggered = False
    question = None
    for trigger in ["!cortana", "/cortana", "/ai", "!bot", "/bot"]:
        if lower.startswith(trigger):
            question = message[len(trigger):].strip()
            triggered = True
            break

    if not triggered and "cortana" in lower:
        question = message.strip()
        triggered = True

    if triggered:
        if not state.bot_enabled:
            rcon.send_chat(f"@{player_name}: I'm currently offline.")
            return
        if not question:
            rcon.send_chat(f"@{player_name}: You called? Ask me something.")
            return
        ai_queue.try_queue_request(player_name, player_id, question)


def _on_kill_event(event: dict):
    """Newer Reclaimer builds push a "kill" event for every death, e.g.
    {"event":"kill","killer":"<decimal id>","victim":"<decimal id>",
     "report":<int>,"time":<unix>}. Ids are resolved to names from the
    names remembered by server_info's polling (no RCON call here), the
    kill is added to state.kill_feed for the dashboard, and -- when
    config.LOG_KILL_EVENTS is on -- logged. "report" is a per-kill code
    whose meaning isn't known yet (weapon/damage type?). Runs on rcon.py's
    kill worker thread, never the reader thread. This is also the hook for
    exact kill-feed features (down callouts, precise streaks and first
    blood instead of the poll-derived versions in background_tasks)."""
    killer = server_info.resolve_kill_id(event.get("killer")) or "Unknown"
    victim = server_info.resolve_kill_id(event.get("victim")) or "Unknown"
    suicide = event.get("killer") == event.get("victim")
    state.kill_feed.append({
        "time": event.get("time") or int(time.time()),
        "killer": killer,
        "victim": victim,
        "suicide": suicide,
        "report": event.get("report"),
    })
    if config.LOG_KILL_EVENTS:
        suffix = " (suicide)" if suicide else ""
        logger.info(f"[KILL] {killer} -> {victim}{suffix} report={event.get('report')} raw={json.dumps(event, default=str)}")


def watch_chat():
    """Registers the chat event handler and then blocks forever. Kept as
    a blocking call (rather than just registering and returning) so
    main.py's shape stays the same as the ElDewrito version — the actual
    work now happens on rcon.py's reader thread, not on this one."""
    rcon.set_chat_handler(_on_chat_event)
    rcon.set_event_handler("kill", _on_kill_event)
    logger.info("[CHAT] Listening for live chat events over RCON.")
    while True:
        time.sleep(3600)
