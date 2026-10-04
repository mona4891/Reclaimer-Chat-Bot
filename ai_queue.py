"""Per-player cooldown + a small concurrency-limited queue for AI requests."""

import threading
import time

import config
import state
import rcon
import auth
import moderators
import ai_providers


def handle_ai_request(player_name: str, question: str):
    try:
        answer = ai_providers.ask_ai(player_name, question)
        rcon.send_chat(f"@{player_name}: {answer}")
    finally:
        with state.queue_lock:
            state.pending_count -= 1


def try_queue_request(player_name: str, player_uid: str, question: str):
    now = time.time()

    # Skip cooldown and queue limits for owner AND moderators
    if auth.is_owner(player_uid) or moderators.is_mod(player_uid):
        with state.queue_lock:
            if state.pending_count >= config.MAX_QUEUE_SIZE:
                rcon.send_chat(f"@{player_name}: I'm currently occupied.")
                return False
            state.pending_count += 1
        threading.Thread(target=handle_ai_request, args=(player_name, question), daemon=True).start()
        return True

    # Regular players get cooldown and queue limits
    last_ask = state.player_last_ask.get(player_name, 0)
    elapsed = now - last_ask
    if elapsed < state.PLAYER_COOLDOWN:
        remaining = int(state.PLAYER_COOLDOWN - elapsed)
        rcon.send_chat(f"@{player_name}: Please wait {remaining}s before asking again.")
        return False

    with state.queue_lock:
        if state.pending_count >= config.MAX_QUEUE_SIZE:
            rcon.send_chat(f"@{player_name}: I'm currently occupied.")
            return False
        state.pending_count += 1

    state.player_last_ask[player_name] = now
    threading.Thread(target=handle_ai_request, args=(player_name, question), daemon=True).start()
    return True
