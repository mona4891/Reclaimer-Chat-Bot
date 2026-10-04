"""
Shared, runtime-mutable state for Cortana Bot.

Every other module that needs to read or change one of these values does
`import state` and accesses it as `state.some_value`. Modules must not do
`from state import some_value`, because that copies the value at import
time and later changes elsewhere would not be seen — the whole point of
this module is to be the single shared source of truth that every command
and background thread reads from and writes to, the same way the globals
in the original single-file script worked.
"""

import threading
from collections import deque

import config

# ── Bot feature toggles ───────────────────────
# No rotation_enabled/voting_enabled/shouldannounce_enabled here — those
# backed ElDewrito RCON settings (Server.VotingEnabled, Server.
# ShouldAnnounce, map rotation) with no Reclaimer equivalent. Map/mode
# and votes are driven on demand by commands_game.py instead.
bot_enabled = True
local_enabled = False
memory_enabled = False
automod_enabled = False
announce_enabled = True
afk_enabled = False
discord_enabled = False
stats_enabled = True
voice_enabled = False
load_balancing_enabled = False
callouts_enabled = False

# ── Cooldowns & request queue ─────────────────
PLAYER_COOLDOWN = config.PLAYER_COOLDOWN_DEFAULT
player_last_ask = {}
queue_lock = threading.Lock()
pending_count = 0
chat_memory = deque(maxlen=config.CHAT_MEMORY_SIZE)

# ── Game state ─────────────────────────────────
# No available_variants/available_maps/rotation/rotation_index here —
# those backed the ElDewrito-era map/mode rotation feature, which the bot
# no longer runs (see background_tasks.py's module docstring).
known_players = set()
afk_tracker = {}

# Most recent kills from the server's `kill` events (newest last), filled
# by chat_watcher._on_kill_event() and served to the dashboard at
# /api/kills. Each entry: {"time", "killer", "victim", "suicide", "report"}.
kill_feed = deque(maxlen=100)
last_game_status = ""
first_blood_given = False

# Per-player snapshot used by background_tasks.check_callouts() to notice
# changes (going down, a betrayal, a suicide) since the last check. Keyed
# by player name.
callout_tracker = {}

# Name of whoever check_callouts() last announced as the sole score
# leader — reset to None whenever a match isn't in progress, so a new
# match always starts with a clean slate rather than immediately
# announcing a "lead change" against the previous match's leader.
last_leader = None

# ── AI provider state ─────────────────────────
active_provider = "auto"
provider_failures = {}
current_provider_index = 0

# ── Credentials & server config (populated from config.txt) ──
GROQ_API_KEY = ""
CEREBRAS_API_KEY = ""
MISTRAL_API_KEY = ""
OPENROUTER_API_KEY = ""

RCON_PASSWORD = ""
RCON_PORT = config.RCON_PORT_DEFAULT
OWNER_UUID = ""
OWNER_PRIVKEY = ""

DISCORD_WEBHOOK_URL = ""
DISCORD_BOT_TOKEN = ""
DISCORD_CHANNEL_ID = ""


def apply_config(cfg: dict):
    """Load values from a config dict (as returned by config.load_config()) into state."""
    global GROQ_API_KEY, CEREBRAS_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY
    global RCON_PASSWORD, RCON_PORT, OWNER_UUID, OWNER_PRIVKEY
    global DISCORD_WEBHOOK_URL, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID

    GROQ_API_KEY = cfg.get("GROQ_API_KEY", "")
    CEREBRAS_API_KEY = cfg.get("CEREBRAS_API_KEY", "")
    MISTRAL_API_KEY = cfg.get("MISTRAL_API_KEY", "")
    OPENROUTER_API_KEY = cfg.get("OPENROUTER_API_KEY", "")
    RCON_PASSWORD = cfg.get("RCON_PASSWORD", "")
    RCON_PORT = int(cfg.get("RCON_PORT", config.RCON_PORT_DEFAULT))
    OWNER_UUID = cfg.get("OWNER_UUID", "").lower().replace("0x", "")
    OWNER_PRIVKEY = cfg.get("OWNER_PRIVKEY", "")
    DISCORD_WEBHOOK_URL = cfg.get("DISCORD_WEBHOOK_URL", "")
    DISCORD_BOT_TOKEN = cfg.get("DISCORD_BOT_TOKEN", "")
    DISCORD_CHANNEL_ID = cfg.get("DISCORD_CHANNEL_ID", "")
