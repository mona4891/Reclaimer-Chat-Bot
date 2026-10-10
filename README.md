# Cortana Bot for Project Reclaimer

An AI chat and moderation bot for [Project Reclaimer](https://projectreclaimer.dev)
Halo 3 PC dedicated servers. Players talk to Cortana in game chat, moderators
run the server through `!ai` commands, and a local web dashboard gives you
buttons for all of it.

It started as a port of an ElDewrito bot. The transport and moderation layers
were rewritten for Reclaimer's RCON WebSocket protocol, which is documented in
the server's `RCON.md` (tested against servers 0.8.11 to 0.8.15).

## Features

- **AI chat:** ask with `!cortana <question>` or just mention "cortana". Providers are Groq, Cerebras, Mistral and OpenRouter, with automatic fallback and optional web search.
- **Moderation:** kick, ban (including players who aren't connected), timed bans and mutes with reasons, warnings (3 warnings kicks), auto-mod, AFK kick and a moderator roster. Actions are credited to whoever ran them ("Bravo was kicked by Alice.").
- **Game control:** change map and mode, queue the next game, shuffle, set team count, move a player between teams, end a round or game, run votes.
- **Server admin:** rename the server, set or clear the join password, limit join ping, manage VPN allowances.
- **Live player data:** service tag, alive state, health, shields and time since last death.
- **Kill feed and activity feed:** every death with names, plus joins, leaves, kicks, bans, votes, anti-cheat flags and the outcome of queued actions.
- **Match features:** callouts (first blood, kill streaks, betrayals, lead changes), match summaries, persistent player stats and a Discord bridge.
- **Web dashboard:** a single HTML file for status, players, activity, game control, moderation and settings.

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
| `RCON_PASSWORD` | The password under `[rcon]` in your server's `dedicated.toml` (8 to 128 characters). |
| `RCON_PORT` | Each server answers RCON on **TCP at its own game port number**, so the server on UDP 49176 uses TCP 49176. `dedicated check` shows the ports. |
| `OWNER_UUID` | **Your Reclaimer player ID**: the 64-character hex string shown in the `players` and `bans` output. |
| `OWNER_PRIVKEY` | A secret you choose. It enables owner commands and authenticates the dashboard. |
| `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | AI provider keys. |
| `DISCORD_BOT_TOKEN` | Optional, for the Discord bridge. |

The server's RCON listens on `127.0.0.1` by default, so the bot has to run on the
same machine. For another machine, use an SSH tunnel or a VPN (RCON is not
encrypted), or set `[rcon] address` in `dedicated.toml` and allow only the bot's
address through the firewall. Set `RCON_HOST` in `config.py` to match.

`config.txt` holds your secrets and is listed in `.gitignore`. Don't commit it.

The server allows 4 signed-in tools at once. If the console is full the bot logs
that and retries. Five wrong passwords from one address lock it out for ten
minutes, so after three rejected sign-ins in a row the bot pauses its reconnect
attempts for eleven minutes instead of retrying.

## Commands

Everything is typed in game chat with the `!ai` prefix. Name a player by their
name (quote names with spaces), their `#number` from `players`, or their player ID.

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

**Moderation:**

| Command | What it does |
|---|---|
| `kick <player> [reason]` | Removes the player and blocks their ID, IP and device for 10, 30, 60, then 120 minutes on successive kicks. |
| `ban <player> [time] [reason]` | Bans a connected player's ID, IP and device together. `time` is `90s`, `30m`, `12h`, `7d` or `2w`; leave it out for a permanent ban. |
| `ban <player ID \| IP \| range> [time] [reason]` | Bans someone who isn't connected, for example `ban 198.51.100.0/24 7d abuse`. |
| `tempban <player> [time]` | A timed ban. `time` is a server time or plain minutes; the default is 5 minutes. |
| `unban <name \| ID \| device \| IP \| range>` | Lifts the whole matching ban, including its linked entries. A name only works if exactly one active ban has it; otherwise the server says so and you use the ID or IP from `banlist`. |
| `banlist` | The first five active bans, with time left. |
| `mute <player> [time] [reason]`, `unmute <player>` | Nobody hears the player's text or voice. Without a time, a mute lasts until `unmute` or a server restart. |
| `warn <player> <reason>`, `warnings <player>`, `clearwarnings <player>` | Warnings; the third kicks. |
| `tell <player> <message>`, `stats [player]` | Private message; stored stats. |

Kicks, bans, mutes and votes against the server owner are refused, and
moderators can't act against other moderators (only the owner can).

**Game control:**

| Command | What it does |
|---|---|
| `maps`, `modes` | List installed maps and modes. Use the names shown. |
| `map <map>` | Load a map, keeping the current game rules. |
| `mode <mode>` | Load a mode or saved game variant, keeping the current map. |
| `load <map> <mode>` | Load both. Quote names with spaces. |
| `nextmap [<map> [<mode>]]` | With no arguments, shows the next-game override. Otherwise queues a game without ending this one; an omitted mode keeps the current rules. |
| `teamcount [2-8]` | With no argument, shows the occupied teams. Otherwise queues a redistribution over that many teams. |
| `shuffle` | Queue a balanced shuffle. |
| `team <player> <team>` | Move a player to `red`, `blue`, `green`, `orange`, `purple`, `gold`, `brown` or `pink`. A team's last player can't be moved during a round. |
| `endround`, `endgame` | End the round (the leader wins it) or the game with the scores as they stand. |
| `vote` | Show the running vote and its tally, plus the playlist ballot. |
| `startvote <endround\|endgame\|shuffle\|kick <player>\|playlist>` | Start a vote. |
| `passvote`, `cancelvote` | Pass or cancel the running vote or playlist ballot. |
| `maxping [<ms>\|off]` | Show or set the highest ping a player may have *as they join* (up to 1000). |
| `vpn [IP]` | VPN-blocking status, or whether the server refuses that address. |

### Owner only

`addmod <player>`, `removemod <player>`, `backup`, `backuplist`,
`restore <name>`, `discord on|off`, `debugall`, plus:

| Command | What it does |
|---|---|
| `servername [<name>]` | Show or rename the server. |
| `password [<value> \| clear]` | With no argument, shows whether a join password is required (never the password). Otherwise sets it; `clear` sends `password ""`. |
| `vpnallow <player \| ID \| IP \| range> [note]` | Let someone join through a VPN on every server sharing the ban list. For a refused player use the ID from their `refused` activity line. |
| `vpnrevoke <ID \| IP \| range>` | Take an allowance back, written exactly as it was allowed. |

### Game control notes

- `map`, `mode` and `load` end the current game and apply in the next ready lobby. `nextmap` waits for that lobby without ending the game. The server's reply only means the change was queued; when it can't be completed, the server sends a `control` event and the bot posts "Load failed: ..." in chat.
- Name, password and ping-limit changes last until the server restarts. They don't touch `dedicated.toml`.
- The server's own error text is relayed to chat, so a typo is obvious.
- A join password typed in chat is visible to everyone in the lobby. The bot keeps it out of its own log, the AI's context and the Discord bridge, but can't hide it from players. Setting it from the dashboard avoids this.
- Still unsupported, because Reclaimer's RCON has no equivalent: bot-driven map rotation, `shouldannounce`, `reloadvoting` and the old `voting*` settings.

## Who gets the credit

Commands that change something are sent with a `by` name, which players read
instead of "an admin" and which the server's audit log records as `Alice (RCON)`.
A chat command is credited to the player who typed it, a dashboard action to the
owner's in-game name, and anything the bot does on its own (auto-mod, AFK kicks)
to the bot. See `rcon.acting_as()`.

## Live player data, kills and events

`players` reports `service_tag`, `alive`, `health`, `shields` and
`seconds_since_last_death`. Health and shields are native fractions (1.0 is
full), and anything unavailable is null. `server_info.py` normalizes them to
`serviceTag`, `isAlive`, `health`, `shields` and `sinceDeath`; they only appear
when the server sends them, and they show up in the AI's game context, in
`!ai mystats` (as percentages) and on the dashboard.

Every native death produces a `kill` event, suicides and team kills included:

```json
{"event": "kill", "killer": "<engine id or null>", "victim": "<engine id>", "report": 20, "time": 1790929780}
```

- The ids are the same engine IDs as `players.engine_id` (and `guest_players.engine_id` for split screen). `server_info.resolve_kill_id()` maps them to names using names remembered from polling, so no RCON call is needed per kill. A null `killer` is shown as "World".
- `report` is the native report byte. Its meaning isn't documented, so it is shown as-is.
- Kills go into an in-memory feed for the dashboard and are logged as `[KILL] Killer -> Victim ...` lines. Set `LOG_KILL_EVENTS = False` in `config.py` to stop the logging (the dashboard feed keeps working).
- First blood and kill streaks still use the older poll-based logic. The `kill` events are the hook for making them exact (see `chat_watcher._on_kill_event`).

All other events (`join`, `leave`, `refused`, `kick`, `ban`, `unban`, `mute`,
`unmute`, `vote`, `phase`, `cheat`, `control`) are summarised into an activity
feed (`state.activity`), logged as `[EVENT]` lines, and shown on the dashboard's
Activity tab. Anti-cheat flags are logged as warnings. A server that falls too
far behind sends a `lagged` message, which the bot logs.

The game phase maps to the bot's internal status like this: `playing`,
`round_over` and `between_rounds` count as in game, `no_game` and `finished`
count as lobby. That is what triggers the match summary when a game ends, without
one after every round of a multi-round game.

## Web dashboard

`reclaimer_dashboard.html` is a single file. Open it in a browser while the bot
is running (the bot serves its API on `127.0.0.1:5000`).

| Tab | What's there |
|---|---|
| Server Status | Bot, players, map, mode, next game, active vote with tally, join password, anti-cheat, VPN blocking, max join ping, RCON link, feature toggles. |
| Players | Live table with service tag, health and shield bars, last died, kick/ban/tempban/mute/warn/vote kick/tell buttons, and the kill feed. |
| Activity | Joins, leaves, kicks, bans, mutes, votes, phase changes, anti-cheat flags and queued-action results, colour-coded. |
| Game Control | Map and mode pickers (loaded from the server), Set Map / Mode / Next Game, Load Map + Mode, End Round / End Game, team count, shuffle, move a player, and the vote buttons. Results show on the page; actions that end the game ask for confirmation. |
| Moderation | Moderator roster, warnings, ban list (ID, IP, device, time left, who banned) with unban, and a form to ban by ID, IP or range. |
| Settings | AI provider, backups, memory, server name and join password, max ping, VPN check/allow/revoke. |
| Commands | A free-text command box and quick buttons for the common commands. |

Kick, ban and mute ask for an optional reason (and a duration for mutes). Failures
show the server's own reason instead of a false success.

**The dashboard asks for your owner key.** The key is `OWNER_PRIVKEY` from
`config.txt`. It is not stored in the HTML file: the first time you use a
control that needs it, the dashboard asks for it and remembers it in that
browser only. Use the "Set dashboard key" button to change or forget it. If the
bot rejects the key, the dashboard forgets it and asks again.

### Dashboard API

All `POST` endpoints need `Authorization: Bearer <OWNER_PRIVKEY>`.

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Bot state, feature toggles, map, mode, phase, next game, vote, password state, anti-cheat, VPN block, max ping, RCON link. |
| `GET /api/players` | Players with score, K/D/A, team, number, engine ID and the live fields above. |
| `GET /api/mods`, `GET /api/bans` | Moderator roster and active bans (one row per ban, linked ID/IP/device entries merged). |
| `GET /api/maps`, `GET /api/modes` | The server's own lists: `entries` (`name`, `reference`, `kind`) and `names` (the references). |
| `GET /api/kills?limit=N` | Recent kills, newest first. |
| `GET /api/activity?limit=N` | Recent server events, newest first. |
| `POST /api/game` | `{"action": "...", "args": "..."}` runs any game-control command (and, as owner, `servername`, `password`, `vpnallow`, `vpnrevoke`) and returns `{"ok": bool, "messages": [...]}`. |
| `POST /api/kick` | `{"name", "reason"?}` |
| `POST /api/ban` | `{"name" (a player, ID, IP or range), "duration"?, "reason"?}` |
| `POST /api/tempban` | `{"name", "duration"}` in minutes. |
| `POST /api/mute`, `/api/unmute` | `{"name", "duration"?, "reason"?}` / `{"name"}` |
| `POST /api/unban` | `{"identifier"}` (ID, device, IP, range or unambiguous name). |
| `POST /api/command`, `/say`, `/feature` | Run any `!ai` command as the owner, speak in chat, toggle features. |

The moderation endpoints answer `{"success": bool, "message": ...}` and use HTTP
502 when the server refuses.

## How it differs from the ElDewrito version

- **One RCON WebSocket, no HTTP status endpoint.** `status` and `players` stand in for the old polling. `server_info.py` merges them and normalizes field names to the shape the rest of the bot already expected.
- **Chat is pushed live,** not tailed from a log file. `chat_watcher.py` registers a handler for chat events.
- **Bans are server-side.** Reclaimer's `ban`/`unban`/`bans` commands manage a ban list shared by every server on the machine, with native durations and ranges. `bans.py` is a thin wrapper.
- **Removed:** `game_maps.py`, `rotation_store.py` and the ban-sweep thread. Reclaimer won't let a banned player stay connected, so there's nothing to sweep.

## Architecture notes

### Threading rule

RCON replies and pushed events share one socket read by a single reader thread.
Anything that sends a command and waits for the reply (including `send_chat`)
must **not** run on that thread. It would block the very thread that delivers
the reply, and every RCON call would time out for 8 seconds. `rcon.py` runs
chat handlers on their own threads and other events (`kill`, and the `*`
catch-all for the rest) on in-order worker queues. Keep this in mind if you
edit `rcon.py` or `chat_watcher.py`.

### Null-safe numbers

The server can send `null` for numeric fields (for example scores between
games). `server_info._num()` turns these into 0 once, so nothing downstream
trips over `None`.

### Reconnects

A reconnect closes the old socket first, so chat is never delivered twice. A
failed or slow command doesn't mark a healthy connection as down, and a failed
poll is skipped rather than treated as "everyone left". Commands are never
retried automatically, because an unanswered moderation command may already
have run.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "No reply from the server in time" | The command may still have worked. Check the game. If it happens on every command, look in the log for `[RCON] Unmatched reply` lines and open an issue with one. |
| "Not connected to the server right now" | The RCON link is down. The bot reconnects on its own; check `RCON_PASSWORD` and `RCON_PORT`. |
| Log says "Console is full" | Four tools are already signed in. Disconnect one (a desktop RCON client, for example). |
| Log says "Pausing reconnects for 11 minutes" | Three sign-ins in a row were rejected. Fix `RCON_PASSWORD` and restart the bot. |
| "Load failed: ..." in chat | The server accepted the command but couldn't finish it (for example the map isn't installed or a player couldn't load it). The reason is the server's. |
| `unban <name>` is refused | Several active bans share that name. Use the exact ID or IP from `banlist`. |
| `team` or `teamcount` is refused | They need a live team round, enough players and a map that supports it. |
| Dashboard shows "Unauthorized" | The key you entered doesn't match `OWNER_PRIVKEY` in `config.txt`. Enter it again with the "Set dashboard key" button. |
| Health, shield or tag columns show `-` | The server didn't send them (older build), or the player has no body right now. |

## Project layout

| Area | Files |
|---|---|
| Foundations | `config.py`, `state.py`, `logger_setup.py` |
| Data stores | `player_stats.py`, `warnings_store.py`, `bans.py`, `moderators.py`, `permanent_memory.py` |
| Server and game | `rcon.py`, `server_info.py`, `auth.py`, `moderation_actions.py`, `automod.py`, `match_summary.py` |
| AI | `ai_providers.py`, `ai_queue.py`, `web_search.py` |
| Commands | `command_router.py`, `commands_misc.py`, `commands_admin.py`, `commands_mod.py`, `commands_game.py` |
| Integrations and loops | `discord_bridge.py`, `tts.py`, `backup_manager.py`, `background_tasks.py`, `chat_watcher.py`, `web_dashboard.py`, `main.py` |
| Front end | `reclaimer_dashboard.html` |
