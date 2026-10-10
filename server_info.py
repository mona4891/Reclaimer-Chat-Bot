"""
Live server info for a Project Reclaimer server.

Unlike ElDewrito's single HTTP JSON endpoint, Reclaimer needs two RCON
commands ("status" and "players") to get the equivalent picture, and its
field names are different (players count is an int here, not the top of
a combined payload; player IDs are called "id" not "uid"; there's still
no timeSpentAlive/bestStreak, though newer builds do report service tag,
alive, health, shields and time since last death). get_server_info()
below merges both replies and normalizes the field names to the SAME
shape the rest of the bot (build_game_context, background_tasks,
commands_mod, web_dashboard...) already expects from the ElDewrito days,
so those modules didn't need a rewrite -- only the fields Reclaimer can't
supply are simply left out, which the rest of the codebase already
handles gracefully via .get()/`in` checks.
"""

import rcon
import state


def _pick(p: dict, *keys):
    """First of `keys` present in the dict, else None. The documented
    per-player keys are service_tag, alive, health, shields (native
    fractions, 0..1) and seconds_since_last_death; the extra spellings
    are only a safety net for other builds."""
    for k in keys:
        if k in p and p[k] is not None:
            return p[k]
    return None


def _num(value, default=0):
    """Numeric field that may arrive as null. dict.get("score", 0) only
    falls back when the key is MISSING, so a server sending "score": null
    (e.g. between games) used to leak None into max()/sorted()/`> 0`
    checks all over the bot and crash them. Coerce here, once."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return default


def fmt_pct(fraction) -> str:
    """Health and shields arrive as native fractions (1.0 = full), not
    percentages. Returns e.g. "75%"."""
    try:
        return f"{round(float(fraction) * 100)}%"
    except (TypeError, ValueError):
        return str(fraction)


def kill_id_matches(kill_id, player_id_hex: str) -> bool:
    """`kill` events identify killer/victim by a decimal 64-bit number,
    not the 64-hex-char player id that `players` uses. Observed
    relationship (3 of 3 sampled players): the number is the first 8 bytes
    of the hex id read little-endian, with the top bit (bit 63) set."""
    try:
        raw = bytes.fromhex(str(player_id_hex)[:16])
        if len(raw) != 8:
            return False
        return (int.from_bytes(raw, "little") | (1 << 63)) == int(kill_id)
    except (ValueError, TypeError):
        return False


_kill_name_cache = {}   # decimal kill id (int) -> last known player name


def kill_id_for(player_id_hex: str):
    """Decimal id that `kill` events use for this player, or None."""
    try:
        raw = bytes.fromhex(str(player_id_hex)[:16])
        if len(raw) != 8:
            return None
        return int.from_bytes(raw, "little") | (1 << 63)
    except (ValueError, TypeError):
        return None


def resolve_kill_id(kill_id, players=None):
    """Player name for a kill event's killer/victim id. Checks `players`
    (if given), then names remembered from earlier polls -- so a kill is
    still attributed correctly if the player has since left, and kill
    handling needs no RCON call of its own. None if never seen (and for a
    null id, which a kill event uses for an unidentified/world killer)."""
    if kill_id is None:
        return None
    for p in players or []:
        if kill_id_matches(kill_id, p.get("uid", "")):
            return p.get("name", "?")
    try:
        return _kill_name_cache.get(int(kill_id))
    except (TypeError, ValueError):
        return None


def get_server_info() -> dict:
    status_data = rcon.send_command("status")
    if status_data is None:
        return {}
    players_data = rcon.send_command("players") or {}
    raw_players = players_data.get("players", [])

    normalized_players = []
    for p in raw_players:
        normalized_players.append({
            "name": p.get("name", "?"),
            "uid": p.get("id", ""),          # Reclaimer calls this "id"
            "ip": p.get("ip", ""),
            "number": p.get("number"),
            "score": _num(p.get("score")),
            "kills": _num(p.get("kills")),
            "deaths": _num(p.get("deaths")),
            "assists": _num(p.get("assists")),
            "betrayals": _num(p.get("betrayals")),
            "suicides": _num(p.get("suicides")),
            "muted": p.get("muted", False),
            "admin": p.get("admin", False),
            "team": p.get("team"),
        })

        # Live fields added in newer Reclaimer builds. Only set when the
        # server actually sent them, so callers' `"isAlive" in p` /
        # `p.get("serviceTag")` checks keep no-op'ing on older servers
        # instead of showing wrong data. Still no Reclaimer equivalent
        # for roundScore, timeSpentAlive, bestStreak, primaryColor, emblem.
        entry = normalized_players[-1]
        tag = _pick(p, "service_tag", "serviceTag", "tag")
        alive = _pick(p, "alive", "is_alive", "isAlive")
        health = _pick(p, "health")
        shields = _pick(p, "shields", "shield")
        since_death = _pick(p, "seconds_since_last_death", "last_death", "last_died",
                            "died_ago", "since_death", "time_since_death", "timeSinceDeath")
        engine_id = p.get("engine_id")
        if engine_id not in (None, ""):
            entry["engineId"] = str(engine_id)
        if p.get("guests"):
            entry["guests"] = p.get("guests")
        if tag is not None:
            entry["serviceTag"] = tag
        if alive is not None:
            entry["isAlive"] = bool(alive)
        if health is not None:
            entry["health"] = health
        if shields is not None:
            entry["shields"] = shields
        if since_death is not None:
            entry["sinceDeath"] = since_death   # raw value as the server sends it

    # Remember engine id -> name for kill-event attribution (see
    # resolve_kill_id). `kill` events carry the same decimal engine ids as
    # players.engine_id and guest_players.engine_id (split-screen guests).
    if len(_kill_name_cache) > 2000:
        _kill_name_cache.clear()
    for p in normalized_players:
        if not p.get("name"):
            continue
        for key in (p.get("engineId"), kill_id_for(p.get("uid", ""))):
            try:
                if key not in (None, ""):
                    _kill_name_cache[int(key)] = p["name"]
            except (TypeError, ValueError):
                pass
    for g in players_data.get("guest_players") or []:
        if not isinstance(g, dict):
            continue
        try:
            gid = int(g.get("engine_id"))
        except (TypeError, ValueError):
            continue
        host = next((p["name"] for p in normalized_players if p.get("uid") == g.get("host_id")), "")
        _kill_name_cache[gid] = g.get("name") or (f"{host} (guest)" if host else "Guest")

    # Reclaimer's status reply has no explicit "teams enabled" flag; infer
    # it from whether any connected player actually has a team assigned.
    teams_enabled = any(p.get("team") is not None for p in normalized_players)

    return {
        # Normalized to match the old ElDewrito shape so build_game_context()
        # and every background thread that checks status=="InGame"/"InLobby"
        # keep working unchanged. Documented phases: no_game, playing,
        # round_over, between_rounds, finished. The three mid-game ones
        # count as InGame so a multi-round match isn't summarised after
        # every round; no_game and finished count as InLobby, which is what
        # triggers the match summary when a game ends.
        "status": "InGame" if status_data.get("phase") in ("playing", "round_over", "between_rounds") else "InLobby",
        "map": status_data.get("map", "unknown"),
        "variant": status_data.get("mode", "unknown"),
        "numPlayers": _num(status_data.get("players"), len(normalized_players)),
        "maxPlayers": _num(status_data.get("max_players")),
        "teams": teams_enabled,
        "players": normalized_players,
        # Reclaimer-specific extras with no ElDewrito equivalent, exposed
        # for anything that wants them (gamestatus, the dashboard):
        "server_name": status_data.get("name", ""),
        "address": status_data.get("address", ""),
        "phase": status_data.get("phase", "unknown"),
        "votes_enabled": status_data.get("votes"),
        "text_chat": status_data.get("text_chat"),
        "voice": status_data.get("voice"),
        # Newer status fields (shapes beyond None aren't documented, so
        # these are passed through untouched for the dashboard to show):
        "mode": status_data.get("mode", ""),
        "next_game": status_data.get("next"),
        "vote": status_data.get("vote"),
        "playlist_vote": status_data.get("playlist_vote"),
        "password_required": status_data.get("password_required"),
        "hidden": status_data.get("hidden"),
        "anti_cheat": status_data.get("anti_cheat"),
        "anti_cheat_active": status_data.get("anti_cheat_active"),
        "block_vpn": status_data.get("block_vpn"),
        "max_ping": status_data.get("max_ping"),
    }


def get_player_info(name: str) -> dict:
    for p in get_server_info().get("players", []):
        if p.get("name", "").lower() == name.lower():
            return p
    return {}


def build_game_context() -> str:
    info = get_server_info()
    if not info:
        return "Game state unavailable."
    players = info.get("players", [])
    map_name = info.get("map", "unknown")
    mode = info.get("variant", "unknown")
    num_players = info.get("numPlayers", 0)
    max_players = info.get("maxPlayers", 0)
    status = info.get("status", "unknown")
    teams = info.get("teams", False)

    player_lines = []
    for p in players:
        display_name = p.get("name", "?")
        line = (
            f"  {display_name} — Score:{p.get('score',0)} "
            f"K:{p.get('kills',0)} A:{p.get('assists',0)} D:{p.get('deaths',0)}"
        )
        if teams:
            line += f" Team:{p.get('team','?')}"

        # Only shown when they've actually happened — a "Betrayals:0" or
        # "Suicides:0" on every line would just be noise.
        if p.get("serviceTag"):
            line += f" Tag:{p.get('serviceTag')}"
        if "isAlive" in p:
            line += " [ALIVE]" if p["isAlive"] else " [DEAD]"
        if p.get("isAlive") and "health" in p:
            line += f" Health:{fmt_pct(p.get('health'))}"
            if "shields" in p:
                line += f" Shields:{fmt_pct(p.get('shields'))}"
        if p.get("betrayals"):
            line += f" Betrayals:{p.get('betrayals')}"
        if p.get("suicides"):
            line += f" Suicides:{p.get('suicides')}"
        if p.get("muted"):
            line += " [MUTED]"

        player_lines.append(line)

    if players:
        leader = max(players, key=lambda p: p.get("score", 0))
        winner_line = f"Leading: {leader.get('name','?')} ({leader.get('score',0)} pts)"
    else:
        winner_line = "No scores yet."

    header = f"Game: {map_name} | {mode} | {status} | {num_players}/{max_players} players\n{winner_line}"
    players_block = "Players:\n" + "\n".join(player_lines) if player_lines else "Players: none"
    return f"{header}\n{players_block}"


def build_chat_context() -> str:
    if not state.chat_memory:
        return ""
    return "Recent chat:\n" + "\n".join(f"  {n}: {m}" for n, m in state.chat_memory)


def find_player_name(args: list, start_index: int = 0) -> tuple:
    """
    Find a player name from command arguments.
    Returns (player_name, next_index) where next_index is where the rest starts.
    """
    players = get_server_info().get("players", [])
    player_names = [p.get("name", "") for p in players]

    # Try from longest to shortest possible name (max 5 words)
    max_words = min(5, len(args) - start_index)
    for word_count in range(max_words, 0, -1):
        possible_name = " ".join(args[start_index:start_index + word_count])
        if possible_name.startswith("@"):
            possible_name = possible_name[1:]
        for p_name in player_names:
            if p_name.lower() == possible_name.lower():
                return possible_name, start_index + word_count

    # If no exact match, return first word as name
    first_arg = args[start_index]
    if first_arg.startswith("@"):
        first_arg = first_arg[1:]
    return first_arg, start_index + 1


def get_target_name(args: list) -> tuple:
    """Extract player name from args (supports @ prefix and multi-word names). Returns (name, next_index)."""
    first_arg = args[0]
    if first_arg.startswith("@"):
        args[0] = first_arg[1:]

    return find_player_name(args, 0)
