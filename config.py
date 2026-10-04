"""
Static configuration for Cortana Bot (Project Reclaimer edition).

Everything in this module is either a fixed constant or is loaded once
from config.txt via load_config(). Nothing here changes while the bot is
running (runtime-mutable values like toggles and credentials live in
state.py instead).
"""

import os

# ─────────────────────────────────────────────
#  FILES & PATHS
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.txt")
MEMORY_FILE = os.path.join(BASE_DIR, "memory.txt")
MODS_FILE = os.path.join(BASE_DIR, "mods.json")
MATCH_LOG_FILE = os.path.join(BASE_DIR, "match_history.json")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")
WARNINGS_FILE = os.path.join(BASE_DIR, "warnings.json")
BAN_LOG_FILE = os.path.join(BASE_DIR, "ban_log.txt")
WARNING_LOG_FILE = os.path.join(BASE_DIR, "warning_log.txt")
# No GAME_VARIANTS_DIR / GAME_MAPS_DIR / ELDEWRITO_BAN_LIST here — those
# were ElDewrito install-folder paths for map/mode scanning and its own
# banlist.txt. Map/mode names now come from the server's own RCON `maps`/
# `modes` commands (see commands_game.py), and its ban list lives server-side, managed entirely through RCON
# ban/unban/bans commands (see bans.py) rather than a local file this bot
# reads or writes.

# ─────────────────────────────────────────────
#  BACKUP SYSTEM
# ─────────────────────────────────────────────
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Files to back up
FILES_TO_BACKUP = [
    "stats.json",
    "warnings.json",
    "mods.json",
    "memory.txt",
    "match_history.json",
    "config.txt",
]

# Maximum number of backups to keep (0 = unlimited)
MAX_BACKUPS = 30

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "cortana.log")

# ─────────────────────────────────────────────
#  STATIC CONFIG
# ─────────────────────────────────────────────
# Project Reclaimer's RCON listens as a plain WebSocket on the server's
# own game port (TCP), not a separate port the way ElDewrito split RCON
# (11776) from its HTTP API (11775) — there is no separate HTTP API here
# at all; everything (status, players, chat events, moderation) goes
# through this one RCON socket. See rcon.py's module docstring for the
# full reverse-engineered protocol.
RCON_HOST = "localhost"
RCON_PORT_DEFAULT = 49176
BOT_NAME = "Cortana"
BOT_PREFIX = "Cortana:"
PLAYER_COOLDOWN_DEFAULT = 30
MAX_QUEUE_SIZE = 3
CHAT_MEMORY_SIZE = 100

# ─────────────────────────────────────────────
#  CHAT LENGTH
# ─────────────────────────────────────────────
# Reclaimer's confirmed per-line chat limit is 360 characters. If it
# changes again in a future Reclaimer update, just update
# CHAT_LINE_LIMIT to match (CHAT_TOTAL_LIMIT can stay a couple times
# CHAT_LINE_LIMIT so a full answer still fits in a line or two).
CHAT_LINE_LIMIT = 360     # max characters per individual "say" line sent to RCON
CHAT_TOTAL_LIMIT = 720    # max characters kept from the AI's full answer before it's split into lines

OLLAMA_API = "http://localhost:11434"
OLLAMA_MODEL = "huihui_ai/gemma3-abliterated:1b"

AFK_TIMEOUT_MINUTES = 0
AFK_CHECK_INTERVAL = 60

# ─────────────────────────────────────────────
#  PROACTIVE CALLOUTS
# ─────────────────────────────────────────────
# Cortana can comment unprompted on notable in-match moments — a
# betrayal, a suicide, or a change in the score leader — using fields
# Reclaimer's RCON already sends live (server_info.py), no extra setup
# needed. There's no "down"/kill-feed callout yet: newer Reclaimer builds
# do report alive state and push a `kill` event per death, but the bot
# only logs those events for now (see LOG_KILL_EVENTS) until their exact
# fields are confirmed.
CALLOUT_CHECK_INTERVAL = 8

ANNOUNCEMENTS = [
    "Welcome to our server! Type !cortana <question> to ask Cortana anything or just mention my name.",
    "Reminder: keep it friendly in chat. Type !ai remember <note> to save server notes.",
]
ANNOUNCEMENT_INTERVAL = 600

# Reused by check_game_state()'s match-end polling — the name is a
# holdover from the old rotation feature, which Reclaimer doesn't
# support (see background_tasks.py's module docstring), but the interval
# itself still paces that poll loop.
ROTATION_CHECK_INTERVAL = 5

IGNORED_SENDER_NAMES = {"bot"}

# ─────────────────────────────────────────────
#  KEYWORDS & PATTERNS
# ─────────────────────────────────────────────
CURRENT_INFO_KEYWORDS = [
    "today", "now", "current", "latest", "recent", "news", "right now",
    "score", "winner", "update", "new", "release", "weather", "temperature",
    "price", "cost", "stock", "crypto", "bitcoin", "match", "date", "time"
]
EXPLICIT_SEARCH_KEYWORDS = [
    "search", "find", "look up", "google", "youtube", "video", "watch", "link", "url"
]

SLUR_PATTERNS = [
    r'\bn[i!1]+g+[e3]+r\b', r'\bf+a+g+[o0]+t\b', r'\bk+[i!1]+k+[e3]\b',
    r'\bs+p+[i!1]+c\b', r'\br+[e3]+t+[a4]+r+d\b'
]

SPAM_THRESHOLD = 5
SPAM_WINDOW = 10
CAPS_THRESHOLD = 0.7
CAPS_MIN_LENGTH = 15
WARN_KICK_THRESHOLD = 3
WARN_TEMPBAN_DURATION = 5

# ─────────────────────────────────────────────
#  PERMISSIONS
# ─────────────────────────────────────────────
ADMIN_ONLY_CMDS = {
    "addmod", "removemod",
    "backup", "restore", "backuplist",
    "discord",
    "servername", "password",   # RCON game control, owner only (commands_game.py)
}

# Game-control commands backed by Reclaimer's RCON map/mode/team/vote
# commands (see commands_game.py). Moderator+. Folded into MOD_CMDS below
# so chat_watcher/command_router recognise them.
GAME_CMDS = {
    "maps", "modes", "map", "mode", "load", "nextmap",
    "teamcount", "shuffle",
    "startvote", "passvote", "cancelvote",
}

# RCON text sent for "!ai password clear". Reclaimer's clear syntax isn't
# documented -- if the server rejects this (the bot relays its error), try
# plain "password" instead.
PASSWORD_CLEAR_COMMAND = 'password ""'

# Log the raw JSON of every "kill" event the server pushes (one line per
# death). Handy while confirming the payload's field names; set False once
# you no longer need it, since busy servers will fill the log.
LOG_KILL_EVENTS = True

# This set is really "recognized multi-word bot commands" for
# chat_watcher.py's routing check, not strictly "mod-only" despite the
# name — most of what's here goes through commands_mod.handle(), which
# does gate on mod_or_owner for everything it dispatches, but a couple
# of names (gamestatus, mystats) are intercepted earlier in
# command_router.py by their own open-to-everyone handler and never
# reach that gate.
#
# Map/mode/team/vote control came back via GAME_CMDS once Reclaimer's
# RCON gained map, mode, load, nextmap, teamcount, shuffle and the vote
# commands. Still absent (no RCON equivalent): bot-driven map rotation,
# shouldannounce, reloadvoting, and the old voting* settings — voting is
# run with startvote/passvote/cancelvote instead. "pm" was renamed to
# "tell" to match Reclaimer's actual command name.
MOD_CMDS = {
    "on", "off", "status", "clear", "cooldown", "automod",
    "kick", "ban", "tempban", "unban", "banlist",
    "warn", "warnings", "clearwarnings",
    "mute", "unmute", "tell",
    "mystats", "stats", "gamestatus",
    "provider", "local", "memory", "forget", "modlist",
    "announce", "afk",
    "say", "voice", "reload", "debugall",
    "callouts",
} | GAME_CMDS

# ─────────────────────────────────────────────
#  SYSTEM PROMPT
# ─────────────────────────────────────────────
# Used by the API providers (Groq/Cerebras/Mistral/OpenRouter) — allowed
# room to actually USE the game/player data it's handed (score, K/A/D,
# betrayals, etc.) instead of skipping it for brevity. Costs a few more
# tokens per reply; CHAT_TOTAL_LIMIT above (via ai_providers.trim()) is
# still the hard ceiling regardless of what's asked for here, and a
# shorter target here means trim() has less work to cut on average.
SYSTEM_PROMPT = (
    "You are Cortana, the AI running this Halo server. Answer in 1-3 "
    "sentences (up to about 50 words) — enough room to actually use the "
    "game and player data you're given. If asked about a stat or other "
    "fact that's in that data, state it plainly and specifically instead "
    "of deflecting, guessing, or inventing a command that doesn't exist. "
    "No lists, no markdown, no preamble. Stay witty but direct, and "
    "always finish the sentence you start."
)

# Separate, shorter prompt for the local Ollama fallback (see
# ai_providers.call_local) — that model is much smaller and given a
# tighter token budget (num_predict), so it needs a prompt sized to
# match rather than the fuller one above, which it would struggle to
# follow and could time out or truncate trying to satisfy.
SYSTEM_PROMPT_LOCAL = (
    "You are Cortana. Answer in 1-2 short sentences. If the data you're "
    "given has the fact being asked about, state it directly instead of "
    "guessing. Be witty but brief."
)


def load_config() -> dict:
    """Load config.txt into a dict, creating a template file if missing."""
    from logger_setup import logger

    config = {}
    if not os.path.exists(CONFIG_FILE):
        logger.info(f"[CONFIG] Creating template at {CONFIG_FILE}")
        with open(CONFIG_FILE, "w") as f:
            f.write("GROQ_API_KEY=your-groq-key-here\n")
            f.write("CEREBRAS_API_KEY=your-cerebras-key-here\n")
            f.write("MISTRAL_API_KEY=your-mistral-key-here\n")
            f.write("OPENROUTER_API_KEY=your-openrouter-key-here\n")
            f.write("RCON_PASSWORD=your-rcon-password\n")
            f.write("RCON_PORT=49176\n")
            f.write("OWNER_UUID=your-reclaimer-player-id-here\n")
            f.write("OWNER_PRIVKEY=your-privkey-here\n")
            f.write("# Discord Bridge (optional)\n")
            f.write("DISCORD_WEBHOOK_URL=your-webhook-url-here\n")
            f.write("DISCORD_BOT_TOKEN=your-bot-token-here\n")
            f.write("DISCORD_CHANNEL_ID=your-channel-id-here\n")
        return config
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if value and "your-" not in value:
                    config[key] = value
    logger.info(f"[CONFIG] Loaded: {', '.join(config.keys())}")
    return config
