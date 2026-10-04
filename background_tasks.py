"""
Background loops: everything that runs continuously on its own daemon
thread — scheduled backups, kill-streak/first-blood/proactive callouts,
match-end handling, AFK kicks, new-player welcomes, and scheduled chat
announcements.

Two things from the original ElDewrito-era cortana_bot are gone here,
not just adapted:
  - check_banned_players() (a sweep that re-kicked anyone already
    banned): Reclaimer enforces its own ban list server-side, so a
    banned player simply can't connect or stay connected in the first
    place — there's nothing for the bot to sweep for.
  - The map/mode auto-rotation block inside what was check_game_state():
    Reclaimer handles playlist rotation/voting natively in-game, and the
    bot doesn't drive a rotation of its own. Moderators can still change
    the map/mode or set the next game by hand (see commands_game.py).

main.py starts each of these functions in its own thread; nothing here
starts a thread just by being imported.
"""

import random
import time

import config
import state
import rcon
import auth
import moderators
import backup_manager
import match_summary
import server_info
from logger_setup import logger


def scheduled_backup():
    """Run automatic backups daily."""
    last_backup = 0
    while True:
        time.sleep(3600)  # Check every hour
        now = time.time()
        if now - last_backup >= 86400:  # 24 hours
            backup_manager.create_backup()
            last_backup = now
            logger.info("Scheduled daily backup completed")


def check_killstreaks():
    """Reclaimer's live player data has no "bestStreak" field the way
    ElDewrito's did, so the current kill streak is derived locally
    instead: each poll, a player's streak grows by however many kills
    they picked up since the last poll, and resets to 0 the moment their
    death count goes up. This only tracks the CURRENT streak (not an
    all-time best), which is what actually matters for a live callout
    anyway."""
    streak_tracker = {}   # name -> {"kills": int, "deaths": int, "streak": int}
    streak_announced = {}  # name -> last announced streak value
    while True:
        time.sleep(10)
        if not state.bot_enabled:
            continue
        try:
            current_names = set()
            for p in server_info.get_server_info().get("players", []):
                name = p.get("name", "")
                if not name:
                    continue
                current_names.add(name)
                kills = p.get("kills", 0)
                deaths = p.get("deaths", 0)

                prev = streak_tracker.get(name)
                if prev is None:
                    # First sighting — set the baseline, don't assume a
                    # streak they built up before the bot started watching.
                    streak_tracker[name] = {"kills": kills, "deaths": deaths, "streak": 0}
                    continue

                if deaths > prev["deaths"]:
                    streak = 0
                else:
                    streak = prev["streak"] + max(0, kills - prev["kills"])
                streak_tracker[name] = {"kills": kills, "deaths": deaths, "streak": streak}

                last_announced = streak_announced.get(name, 0)
                if streak >= 5 and streak != last_announced and streak % 5 == 0:
                    streak_announced[name] = streak
                    msgs = {
                        5:  f"{name} is on a killing spree. Impressive, I suppose.",
                        10: f"{name} with 10 kills straight. Someone's having a good day.",
                        15: f"{name} at 15. I'd recommend the others reconsider their strategy.",
                        20: f"{name} is unstoppable. Statistically speaking, anyway.",
                    }
                    rcon.send_chat(msgs.get(streak, f"{name} is on a {streak}-kill streak."))

            for stale in set(streak_tracker) - current_names:
                streak_tracker.pop(stale, None)
                streak_announced.pop(stale, None)
        except Exception:
            pass


def check_first_blood():
    kill_tracker = {}
    while True:
        time.sleep(5)
        if not state.bot_enabled:
            continue
        try:
            info = server_info.get_server_info()
            status = info.get("status", "")
            if status == "InGame" and not state.first_blood_given:
                for p in info.get("players", []):
                    name = p.get("name", "")
                    kills = p.get("kills", 0)
                    prev = kill_tracker.get(name, 0)
                    if kills == 1 and prev == 0:
                        rcon.send_chat(f"First blood — {name}!")
                        state.first_blood_given = True
                        break
                    kill_tracker[name] = kills
            elif status == "InLobby":
                state.first_blood_given = False
                kill_tracker.clear()
        except Exception:
            pass


def check_game_state():
    """Watches for a match ending (InGame -> InLobby) and announces/logs
    the result via match_summary. No rotation follow-up — see module
    docstring for why."""
    while True:
        time.sleep(config.ROTATION_CHECK_INTERVAL)
        if not state.bot_enabled:
            continue
        try:
            info = server_info.get_server_info()
            if not info:
                continue   # failed poll: keep the last known status
            status = info.get("status", "")

            if state.last_game_status == "InGame" and status == "InLobby":
                match_summary.process_match_end(info)

            state.last_game_status = status
        except Exception as e:
            logger.info(f"[MATCH] Error: {e}")


def check_afk():
    while True:
        time.sleep(config.AFK_CHECK_INTERVAL)
        if not state.afk_enabled or config.AFK_TIMEOUT_MINUTES == 0 or not state.bot_enabled:
            continue
        try:
            now = time.time()
            info = server_info.get_server_info()
            if info.get("status") != "InGame":
                continue
            for p in info.get("players", []):
                name = p.get("name", "")
                uid = p.get("uid", "")
                kills = p.get("kills", 0)
                score = p.get("score", 0)
                if auth.is_owner(uid) or moderators.is_mod(uid):
                    continue
                prev = state.afk_tracker.get(name, {"last_kills": kills, "last_score": score, "last_active": now})
                if kills != prev["last_kills"] or score != prev["last_score"]:
                    state.afk_tracker[name] = {"last_kills": kills, "last_score": score, "last_active": now}
                else:
                    idle_min = (now - prev["last_active"]) / 60
                    if idle_min >= config.AFK_TIMEOUT_MINUTES:
                        rcon.send_command(f"kick {rcon.quote_if_needed(name)}")
                        rcon.send_chat(f"{name} was kicked for being AFK.")
                        state.afk_tracker.pop(name, None)
        except Exception:
            pass


def check_players():
    try:
        state.known_players = {p.get("name", "") for p in server_info.get_server_info().get("players", []) if p.get("name", "").strip()}
    except Exception:
        state.known_players = set()

    while True:
        time.sleep(5)
        if not state.bot_enabled:
            continue
        try:
            info = server_info.get_server_info()
            if not info:
                # Poll failed/timed out: don't treat it as "nobody is here",
                # or everyone gets welcomed again when polling recovers.
                continue
            current = {p.get("name", "") for p in info.get("players", []) if p.get("name", "").strip()}
            for name in current - state.known_players:
                if len(name) >= 2:
                    rcon.send_chat(f"Welcome, {name}. Type !cortana <question> or just mention my name.")
            state.known_players = current
        except Exception:
            pass


CALLOUT_MESSAGES_BETRAYAL = [
    "{name} betrayed a teammate. Not a great look.",
    "{name} just shot their own team. Nice.",
    "Friendly fire from {name}. Very friendly.",
]
CALLOUT_MESSAGES_SUICIDE = [
    "{name} managed to kill themselves. Impressive, in a way.",
    "{name} took themselves out. No help needed there.",
    "{name} is their own worst enemy, apparently.",
]
CALLOUT_MESSAGES_LEAD_CHANGE = [
    "{name} just took the lead.",
    "{name} is out in front now.",
    "New leader: {name}.",
]


def check_callouts():
    """
    Watches for notable per-player moments and has Cortana call them out
    in chat unprompted, from fields Reclaimer's RCON already sends live
    (server_info.py) — no extra setup needed.

    No "down" callout yet: newer Reclaimer builds report alive state and
    push a "kill" event per death, but those fields aren't confirmed, so
    chat_watcher only logs the events for now (config.LOG_KILL_EVENTS).

    A player's first appearance in the tracker only sets the baseline
    (betrayal/suicide counts) rather than comparing against defaults —
    otherwise a player who already has betrayals/suicides on their tally
    from before the bot started watching would trigger a false callout
    the moment they're first seen.

    Also announces a change in the sole score leader (needs 2+ players
    and a strict, undisputed lead — a tie announces nothing) — reset
    between matches via state.last_leader so a new match doesn't compare
    against the previous one's leader.
    """
    while True:
        time.sleep(config.CALLOUT_CHECK_INTERVAL)
        if not state.callouts_enabled or not state.bot_enabled:
            continue
        try:
            info = server_info.get_server_info()
            if info.get("status") != "InGame":
                state.last_leader = None
                continue

            players = info.get("players", [])
            current_names = set()

            for p in players:
                name = p.get("name", "")
                if not name:
                    continue
                current_names.add(name)

                prev = state.callout_tracker.get(name)
                first_sight = prev is None
                prev = prev or {}
                updated = dict(prev)

                betrayals = p.get("betrayals", 0)
                if not first_sight and betrayals > prev.get("betrayals", 0):
                    rcon.send_chat(random.choice(CALLOUT_MESSAGES_BETRAYAL).format(name=name))
                updated["betrayals"] = betrayals

                suicides = p.get("suicides", 0)
                if not first_sight and suicides > prev.get("suicides", 0):
                    rcon.send_chat(random.choice(CALLOUT_MESSAGES_SUICIDE).format(name=name))
                updated["suicides"] = suicides

                state.callout_tracker[name] = updated

            # Drop players who've left so a rejoin isn't treated as "still down".
            for stale in set(state.callout_tracker) - current_names:
                state.callout_tracker.pop(stale, None)

            if len(players) >= 2:
                top_score = max(p.get("score", 0) for p in players)
                leaders = [p.get("name", "") for p in players if p.get("score", 0) == top_score]
                if top_score > 0 and len(leaders) == 1:
                    leader = leaders[0]
                    if state.last_leader and leader != state.last_leader:
                        rcon.send_chat(random.choice(CALLOUT_MESSAGES_LEAD_CHANGE).format(name=leader))
                    state.last_leader = leader
        except Exception:
            pass


def scheduled_announcements():
    ann_index = 0
    while True:
        time.sleep(config.ANNOUNCEMENT_INTERVAL)
        if not state.announce_enabled or not state.bot_enabled or not config.ANNOUNCEMENTS:
            continue
        try:
            rcon.send_chat(config.ANNOUNCEMENTS[ann_index % len(config.ANNOUNCEMENTS)])
            ann_index += 1
        except Exception:
            pass
