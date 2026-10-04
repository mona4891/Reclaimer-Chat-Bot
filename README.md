# Cortana Bot for Project Reclaimer

An AI chat and moderation bot for [Project Reclaimer](https://projectreclaimer.dev)
Halo 3 PC dedicated servers. Players talk to Cortana in game chat, moderators
run the server through `!ai` commands, and a local web dashboard gives you
buttons for all of it.

It started as a port of an ElDewrito bot. The transport and moderation layers
were rewritten for Reclaimer's RCON protocol, which isn't publicly documented.
It was reverse-engineered against real running servers (0.8.11, then 0.8.15).
`rcon.py`'s module docstring has the full protocol notes.

## Features

- **AI chat:** ask with `!cortana <question>` or just mention "cortana". Providers are Groq, Cerebras, Mistral and OpenRouter, with automatic fallback and optional web search.
- **Moderation:** kick, ban, tempban, mute, warnings (3 warnings kicks), auto-mod, AFK kick and a moderator roster.
- **Game control from chat or the dashboard:** change map and mode, queue the next map, set team count, shuffle, and run votes.
- **Server admin:** rename the server and set or clear the join password.
- **Live player data:** service tag, alive state, health, shields and time since last death.
- **Kill feed:** every death reported by the server, with names.
- **Match features:** callouts (first blood, kill streaks, betrayals, lead changes), match summaries, persistent player stats and Discord bridge.
- **Web dashboard:** a single HTML file for status, players, game control, moderation and settings.

## Requirements

- Python 3.10+
- A Project Reclaimer dedicated server with RCON enabled
- At least one AI provider key (all optional, but the bot has nothing to say without one)

## Quick start

```
pip install -r requirements.txt
python main.py
```

On first run the bot creates `config.txt` from a template. Fill it in:

| Key | What it is |
|---|---|
| `RCON_PASSWORD` | The RCON password from your server's `dedicated.toml`. |
| `RCON_PORT` | Defaults to `49176`, Reclaimer's game port, which doubles as the RCON port. Check `dedicated.toml` if you changed it. |
| `OWNER_UUID` | **Your Reclaimer player ID**: the long hex string shown in the `players` and `bans` output. Not an ElDewrito-style UID. |
| `OWNER_PRIVKEY` | A secret you choose. It enables owner commands and authenticates the dashboard. |
| `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | AI provider keys. |
| `DISCORD_BOT_TOKEN` | Optional, for the Discord bridge. |

If the bot and the server are on different machines, set `RCON_HOST` in
`config.py` and bind the server's RCON to `0.0.0.0` instead of `127.0.0.1` in
`dedicated.toml`.

`config.txt` holds your secrets and is listed in `.gitignore`. Don't commit it.

## Commands

Everything is typed in game chat with the `!ai` prefix.

### Everyone

| Command | What it does |
|---|---|
| `!cortana <question>`, `!ai <question>`, or mention "cortana" | Ask the AI. |
| `!ai remember <note>` | Save a note to the bot's permanent memory. |
| `!ai mystats` | Your own stats, plus live K/D, score, health and shields if you're in a match. |
| `!ai gamestatus` | Game status, server name, phase and voting on/off. |

### Moderators and owner

**Bot control:** `on`, `off`, `status`, `clear`, `cooldown <seconds>`,
`provider <name|auto>`, `automod on|off`, `afk on|off`, `announce on|off`,
`callouts on|off`, `memory on|off`, `forget`, `voice on|off`, `local on|off`,
`say <text>`, `reload`, `modlist`

**Moderation:** `kick`, `ban`, `tempban <player> [minutes]`, `unban <id|ip>`,
`banlist`, `warn <player> <reason>`, `warnings <player>`,
`clearwarnings <player>`, `mute`, `unmute`, `tell <player> <message>`,
`stats [player]`

**Game control:**

| Command | What it does |
|---|---|
| `maps`, `modes` | List the names the server accepts. |
| `map <name>`, `mode <name>`, `load <...>` | End the current game and start the chosen map/mode in the next lobby. |
| `nextmap <name>` | Set the next game without ending this one. |
| `teamcount <n>` | Spread players over `n` teams. |
| `shuffle` | Shuffle the teams. |
| `startvote <endround\|endgame\|shuffle\|kick <player>\|playlist>` | Start a vote. A kick vote gets the same protections as `!ai kick`: it refuses the server owner and, for non-owners, other moderators. |
| `passvote`, `cancelvote` | Resolve the running vote. |

### Owner only

`addmod <player>`, `removemod <player>`, `backup`, `backuplist`,
`restore <name>`, `discord on|off`, `debugall`,
`servername <name>` and `password <value|clear>` (both last until the server restarts).

### Game control notes

- Arguments go to the server exactly as typed, because the server's argument syntax isn't documented. The server's reply, or its error text, is relayed back so a typo is obvious. Use `!ai maps` and `!ai modes` to see valid names, and quote names with spaces (`!ai map "High Ground"`).
- If `!ai password clear` is rejected, change `PASSWORD_CLEAR_COMMAND` in `config.py` (try plain `password`).
- A join password typed in chat is visible to everyone in the lobby. The bot keeps it out of its own log, the AI's context and the Discord bridge, but can't hide it from players. Setting it from the dashboard avoids this.
- Still unsupported, because Reclaimer's RCON has no equivalent: bot-driven map rotation, `shouldannounce`, `reloadvoting` and the old `voting*` settings.

## Live player data and kill events

`players` reports each player's service tag, alive state, health, shields and
how long ago they last died. `server_info.py` normalizes these to `serviceTag`,
`isAlive`, `health`, `shields` and `sinceDeath`. They only appear when the
server sends them, and they show up in the AI's game context and `!ai mystats`.
The exact key names aren't documented, so `server_info._pick()` accepts a few
spellings for each. If a field doesn't show up, check the raw `players` reply
and add its key there.

The event stream pushes a `kill` event for every death:

```json
{"event": "kill", "killer": "<decimal id>", "victim": "<decimal id>", "report": 20, "time": 1790929780}
```

- `killer` and `victim` are the first 8 bytes of the player's hex ID read little-endian, with the top bit set. `server_info.resolve_kill_id()` maps them back to names, using names remembered from polling, so no RCON call is needed per kill.
- `report` is a per-kill code whose meaning isn't known yet.
- Kills go into an in-memory feed for the dashboard and are logged as `[KILL] Killer -> Victim ...` lines. Set `LOG_KILL_EVENTS = False` in `config.py` to stop the logging (the dashboard feed keeps working).
- First blood and kill streaks still use the older poll-based logic. The `kill` events are the hook for making them exact (see `chat_watcher._on_kill_event`).

## Web dashboard

`reclaimer_dashboard.html` is a single file. Open it in a browser while the bot
is running (the bot serves its API on `127.0.0.1:5000`).

| Tab | What's there |
|---|---|
| Server Status | Bot, players, map, mode, next game, active vote, join password, RCON link, feature toggles. |
| Players | Live table with service tag, health and shield bars, last died, plus kick/ban/tempban/mute/warn/vote kick/tell buttons, and the kill feed. |
| Game Control | Map and mode pickers (loaded from the server), next map, load, team count, shuffle, and all vote buttons. Results show on the page. Actions that end the game ask for confirmation. |
| Moderation | Moderator roster, warnings, ban list with unban. |
| Settings | AI provider, backups, memory, server name and join password. |
| Commands | A free-text command box and quick buttons for the common commands. |

**The dashboard asks for your owner key.** The key is `OWNER_PRIVKEY` from
`config.txt`. It is not stored in the HTML file: the first time you use a
control that needs it, the dashboard asks for it and remembers it in that
browser only. Use the "Set dashboard key" button to change or forget it. If the
bot rejects the key, the dashboard forgets it and asks again.

The vote buttons send `endround`, `endgame`, `shuffle` and `playlist`. If the
server expects different names, change the `VOTE_ARGS` block at the top of the
script.

### Dashboard API

All `POST` endpoints need `Authorization: Bearer <OWNER_PRIVKEY>`.

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Bot state, feature toggles, map, mode, phase, next game, vote, password state, RCON link. |
| `GET /api/players` | Players with score, K/D/A, team and the live fields above. |
| `GET /api/mods`, `GET /api/bans` | Moderator roster and active bans. |
| `GET /api/maps`, `GET /api/modes` | The server's own lists. |
| `GET /api/kills?limit=N` | Recent kills, newest first. |
| `POST /api/game` | `{"action": "...", "args": "..."}` runs any game-control command as the owner and returns `{"ok": bool, "messages": [...]}`. |
| `POST /api/command` | Run any `!ai` command as the owner. |
| `POST /api/kick`, `/ban`, `/tempban`, `/mute`, `/unmute`, `/unban`, `/say`, `/feature` | Moderation and toggles. |

## How it differs from the ElDewrito version

- **One RCON WebSocket, no HTTP status endpoint.** `status` and `players` stand in for the old polling. `server_info.py` merges them and normalizes field names to the shape the rest of the bot already expected.
- **Chat is pushed live,** not tailed from a log file. `chat_watcher.py` registers a handler for chat events.
- **Bans are server-side.** Reclaimer's `ban`/`unban`/`bans` commands manage a ban list, and `bans.py` is a thin wrapper. `ban` accepts a player name, but `unban` needs the ID or IP from `!ai banlist` or the dashboard.
- **Removed:** `game_maps.py`, `rotation_store.py` and the ban-sweep thread. Reclaimer won't let a banned player stay connected, so there's nothing to sweep.

## Architecture notes

### Threading rule

RCON replies and pushed events share one socket read by a single reader thread.
Anything that sends a command and waits for the reply (including `send_chat`)
must **not** run on that thread. It would block the very thread that delivers
the reply, and every RCON call would time out for 8 seconds. `rcon.py` runs
chat handlers on their own threads and other events (`kill`) on in-order worker
queues. Keep this in mind if you edit `rcon.py` or `chat_watcher.py`.

### Null-safe numbers

The server can send `null` for numeric fields (for example scores between
games). `server_info._num()` turns these into 0 once, so nothing downstream
trips over `None`.

### Reconnects

A reconnect closes the old socket first, so chat is never delivered twice. A
failed or slow command doesn't mark a healthy connection as down, and a failed
poll is skipped rather than treated as "everyone left".

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "No reply from the server in time" | The command may still have worked. Check the game. If it happens on every command, check the log for `[RCON] Unmatched reply` lines and open an issue with one. |
| "Not connected to the server right now" | The RCON link is down. The bot reconnects on its own; check `RCON_PASSWORD` and `RCON_PORT`. |
| Every chat line appears twice in the log | You're running an old build with the duplicate-connection bug. Update. |
| `'>' not supported between 'int' and 'NoneType'` | An old build that didn't handle `null` scores. Update. |
| Dashboard shows "Unauthorized" | The key you entered doesn't match `OWNER_PRIVKEY` in `config.txt`. Enter it again with the "Set dashboard key" button. |
| Health, shields or tag columns show `-` | The server's key names differ from the ones the bot guesses. See "Live player data". |
| A vote button is rejected | The server's vote name differs. Edit `VOTE_ARGS` in the dashboard and the usage text in `commands_game.py`. |

## Project layout

| Area | Files |
|---|---|
| Foundations | `config.py`, `state.py`, `logger_setup.py` |
| Data stores | `player_stats.py`, `warnings_store.py`, `bans.py`, `moderators.py`, `permanent_memory.py` |
| Server and game | `rcon.py`, `server_info.py`, `auth.py`, `moderation_actions.py`, `automod.py`, `match_summary.py` |
| AI | `ai_providers.py`, `ai_queue.py`, `web_search.py` |
| Commands | `command_router.py`, `commands_misc.py`, `commands_admin.py`, `commands_mod.py`, `commands_game.py` |
| Integrations and loops | `discord_bridge.py`, `tts.py`, `backup_manager.py`, `background_tasks.py`, `chat_watcher.py`, `web_dashboard.py`, `main.py` |
