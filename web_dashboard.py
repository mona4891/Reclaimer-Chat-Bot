"""
Local web dashboard: a small Flask API (bot status, player list,
moderator list, ban list, and owner-authenticated action endpoints) used
by an external dashboard UI. Runs on its own daemon thread, port 5000.

A few endpoints/toggles from the ElDewrito-era version are gone: rotation
and shouldannounce, which have no Reclaimer equivalent. Map/mode/team/vote
control and the server name/password are back, as POST /api/game (runs
commands_game.py as the owner and returns the result text), with
GET /api/maps and /api/modes feeding the dashboard's dropdowns and
GET /api/kills serving the live kill feed and GET /api/activity the other
server events (joins, kicks, bans, votes, anti-cheat flags, action results).
Everything the dashboard does on the server is credited to the owner's
in-game name ("Bravo was kicked by Alice.").
"""

import logging

from flask import Flask, jsonify, request
from flask_cors import CORS

import state
import rcon
import server_info
import moderators
import moderation_actions
import command_router
import ai_providers
import bans
import config
import commands_game
from logger_setup import logger

web_app = Flask(__name__)
CORS(web_app)  # Allows frontend to call the API


@web_app.route('/api/status', methods=['GET'])
def api_status():
    info = server_info.get_server_info()
    return jsonify({
        'bot_enabled': state.bot_enabled,
        'local_enabled': state.local_enabled,
        'voice_enabled': state.voice_enabled,
        'afk_enabled': state.afk_enabled,
        'callouts_enabled': state.callouts_enabled,
        'discord_enabled': state.discord_enabled,
        'automod_enabled': state.automod_enabled,
        'announce_enabled': state.announce_enabled,
        'load_balancing_enabled': state.load_balancing_enabled,
        'memory_enabled': state.memory_enabled,
        'players_online': len(info.get('players', [])),
        'current_map': info.get('map', 'unknown'),
        'game_status': info.get('status', 'unknown'),
        'server_name': info.get('server_name', ''),
        'active_provider': ai_providers.get_active_provider_name(),
        'mod_count': len(moderators.load_mods()),
        'rcon_connected': rcon.is_connected(),
        'mode': info.get('mode', ''),
        'phase': info.get('phase', ''),
        'next_game': info.get('next_game'),
        'vote': info.get('vote'),
        'playlist_vote': info.get('playlist_vote'),
        'votes_enabled': info.get('votes_enabled'),
        'password_required': info.get('password_required'),
        'max_players': info.get('maxPlayers', 0),
        'anti_cheat': info.get('anti_cheat'),
        'anti_cheat_active': info.get('anti_cheat_active'),
        'block_vpn': info.get('block_vpn'),
        'max_ping': info.get('max_ping'),
    })


@web_app.route('/api/players', methods=['GET'])
def api_players():
    info = server_info.get_server_info()
    players = []
    for p in info.get('players', []):
        players.append({
            'name': p.get('name', '?'),
            'uid': p.get('uid', ''),
            'score': p.get('score', 0),
            'kills': p.get('kills', 0),
            'deaths': p.get('deaths', 0),
            'assists': p.get('assists', 0),
            'muted': p.get('muted', False),
            'admin': p.get('admin', False),
            'team': p.get('team'),
            'number': p.get('number'),
            'engine_id': p.get('engineId'),
            'betrayals': p.get('betrayals', 0),
            'suicides': p.get('suicides', 0),
            # Live fields from newer Reclaimer builds; absent (None) on
            # servers that don't send them.
            'service_tag': p.get('serviceTag'),
            'alive': p.get('isAlive'),
            'health': p.get('health'),
            'shields': p.get('shields'),
            'since_death': p.get('sinceDeath'),
        })
    return jsonify(players)


def _authorized(req) -> bool:
    auth_header = req.headers.get('Authorization')
    return auth_header == f'Bearer {state.OWNER_PRIVKEY}'


@web_app.route('/api/command', methods=['POST'])
def api_command():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    command = data.get('command', '')

    result = execute_web_command(command)
    return jsonify({'result': result})


def _acting():
    """Credit what follows to the owner's in-game name."""
    return rcon.acting_as(_owner_name())


def _moderation_result(ok: bool, messages: list, success_text: str):
    text = ' '.join(messages) if messages else (success_text if ok else 'Failed.')
    body = {'success': bool(ok), 'message': text if not ok else success_text, 'messages': messages}
    return jsonify(body), (200 if ok else 502)


@web_app.route('/api/kick', methods=['POST'])
def api_kick():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    player_name = data.get('name', '')
    if not player_name:
        return jsonify({'error': 'No player name'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_kick("WebDashboard", state.OWNER_UUID, player_name,
                                        str(data.get('reason', '')).strip(), say=messages.append)
    return _moderation_result(ok, messages, f'Kicked {player_name}')


@web_app.route('/api/ban', methods=['POST'])
def api_ban():
    """Body: name (a connected player, or a player ID / IP / range for
    someone who isn't), optional duration ("7d"...) and reason."""
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    target = data.get('name', '') or data.get('target', '')
    if not target:
        return jsonify({'error': 'No player name'}), 400
    duration = str(data.get('duration', '') or '').strip().lower()
    if duration and not bans.is_duration(duration):
        return jsonify({'error': 'Duration must look like 90s, 30m, 12h, 7d or 2w'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_ban("WebDashboard", state.OWNER_UUID, target,
                                       str(data.get('reason', '')).strip(), duration, say=messages.append)
    return _moderation_result(ok, messages, f'Banned {target}')


@web_app.route('/api/tempban', methods=['POST'])
def api_tempban():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    player_name = data.get('name', '')
    duration = data.get('duration', 5)
    if not player_name:
        return jsonify({'error': 'No player name'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_tempban("WebDashboard", state.OWNER_UUID, player_name, duration, say=messages.append)
    return _moderation_result(ok, messages, f'Temp banned {player_name} for {duration} minutes')


@web_app.route('/api/mute', methods=['POST'])
def api_mute():
    """Body: name, optional duration ("30m"...) and reason."""
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    player_name = data.get('name', '')
    if not player_name:
        return jsonify({'error': 'No player name'}), 400
    duration = str(data.get('duration', '') or '').strip().lower()
    if duration and not bans.is_duration(duration):
        return jsonify({'error': 'Duration must look like 90s, 30m, 12h, 7d or 2w'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_mute("WebDashboard", state.OWNER_UUID, player_name, duration,
                                        str(data.get('reason', '')).strip(), say=messages.append)
    return _moderation_result(ok, messages, f'Muted {player_name}')


@web_app.route('/api/unmute', methods=['POST'])
def api_unmute():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    player_name = data.get('name', '')
    if not player_name:
        return jsonify({'error': 'No player name'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_unmute("WebDashboard", state.OWNER_UUID, player_name, say=messages.append)
    return _moderation_result(ok, messages, f'Unmuted {player_name}')


@web_app.route('/api/say', methods=['POST'])
def api_say():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    message = data.get('message', '')
    if not message:
        return jsonify({'error': 'No message'}), 400

    rcon.send_chat(message)
    return jsonify({'success': True, 'message': f'Sent: {message}'})


@web_app.route('/api/feature', methods=['POST'])
def api_feature():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    feature = data.get('feature', '')
    enabled = data.get('enabled', False)

    if feature == 'afk':
        state.afk_enabled = enabled
    elif feature == 'callouts':
        state.callouts_enabled = enabled
    elif feature == 'discord':
        state.discord_enabled = enabled
    elif feature == 'automod':
        state.automod_enabled = enabled
    elif feature == 'announce':
        state.announce_enabled = enabled
    elif feature == 'voice':
        state.voice_enabled = enabled
    elif feature == 'loadbalance':
        state.load_balancing_enabled = enabled
    elif feature == 'memory':
        state.memory_enabled = enabled

    return jsonify({'success': True})


@web_app.route('/api/bans', methods=['GET'])
def api_bans():
    """Return active bans (name/uid/ip/reason/expiry) for the dashboard's
    ban management view. Reclaimer is the source of truth for this — see
    bans.py's module docstring for why there's no local bans.json here."""
    active = bans.get_active_bans()
    return jsonify(active)


@web_app.route('/api/unban', methods=['POST'])
def api_unban():
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    # The server takes a name (only if one active ban has it), player ID,
    # device fingerprint, IP or range, and lifts the whole linked action.
    # The dashboard sends the row's "identifier" (or its uid/ip/name).
    identifier = data.get('identifier') or data.get('uid') or data.get('ip') or data.get('name', '')
    if not identifier:
        return jsonify({'error': 'No identifier'}), 400

    messages = []
    with _acting():
        ok = moderation_actions.do_unban("WebDashboard", identifier, say=messages.append)
    return _moderation_result(ok, messages, f'Unbanned {identifier}')


@web_app.route('/api/mods', methods=['GET'])
def api_mods():
    """Return list of moderators."""
    mods = moderators.load_mods()
    result = []
    for mod in mods:
        result.append({
            'name': mod.get('name', '?'),
            'uid': mod.get('uid', '')
        })
    return jsonify(result)


def _owner_name() -> str:
    """The owner's in-game name if they're connected, else a placeholder."""
    for p in server_info.get_server_info().get("players", []):
        if p.get("uid", "").lower().replace("0x", "") == state.OWNER_UUID.lower().replace("0x", ""):
            return p.get("name", "ServerOwner")
    return "ServerOwner"


@web_app.route('/api/game', methods=['POST'])
def api_game():
    """Run a game-control command (any of config.GAME_CMDS, plus the
    owner-only config.GAME_ADMIN_CMDS: servername, password, vpnallow,
    vpnrevoke) as the owner and return what it would have said in chat:
    {"ok": bool, "messages": [str, ...]}. Body: {"action": "...",
    "args": "..."} with args exactly as you'd type them after the command."""
    if not _authorized(request):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    action = str(data.get('action', '')).strip().lower()
    args = str(data.get('args', '')).split()
    owner_only = config.GAME_ADMIN_CMDS
    if action not in config.GAME_CMDS and action not in owner_only:
        return jsonify({'error': f'Unknown game action: {action}'}), 400

    messages = []
    try:
        owner = _owner_name()
        with rcon.acting_as(owner):
            if action in owner_only:
                ok = commands_game.handle_admin(owner, state.OWNER_UUID, action, args, say=messages.append)
            else:
                ok = commands_game.handle(owner, state.OWNER_UUID, action, args, say=messages.append)
    except Exception as e:
        logger.error(f"Web game action failed: {e}")
        return jsonify({'ok': False, 'messages': [f'Error: {e}']}), 500
    return jsonify({'ok': bool(ok), 'messages': messages})


def _entries_endpoint(command: str, key: str):
    entries, error = commands_game.list_entries(command, key)
    if entries is None:
        return jsonify({'names': [], 'entries': [], 'error': error}), 502
    # `entries`: {name, reference, kind} rows -- send `reference` back to the
    # server. `names` is just the references, for simple callers.
    return jsonify({'names': [e['reference'] for e in entries], 'entries': entries})


@web_app.route('/api/maps', methods=['GET'])
def api_maps():
    """Installed maps as the server lists them (its own `maps` command)."""
    return _entries_endpoint('maps', 'maps')


@web_app.route('/api/modes', methods=['GET'])
def api_modes():
    """Installed modes and saved game variants (its own `modes` command)."""
    return _entries_endpoint('modes', 'modes')


@web_app.route('/api/activity', methods=['GET'])
def api_activity():
    """Recent joins, leaves, kicks, bans, mutes, votes, phase changes,
    anti-cheat flags and queued-action results, newest first.
    ?limit=N (default 40, max 200)."""
    try:
        limit = max(1, min(int(request.args.get('limit', 40)), 200))
    except ValueError:
        limit = 40
    return jsonify(list(state.activity)[-limit:][::-1])


@web_app.route('/api/kills', methods=['GET'])
def api_kills():
    """Most recent kills, newest first: [{time, killer, victim, suicide,
    report}]. ?limit=N (default 25, max 100)."""
    try:
        limit = max(1, min(int(request.args.get('limit', 25)), 100))
    except ValueError:
        limit = 25
    return jsonify(list(state.kill_feed)[-limit:][::-1])


def execute_web_command(command: str) -> str:
    """Execute a bot command from web interface."""
    try:
        if command.startswith('!ai '):
            remaining = command[4:].strip()

            owner_name = _owner_name()

            command_router.handle_command(owner_name, state.OWNER_UUID, "", remaining)
            return f"Command executed: {command}"
        else:
            return f"Unknown command format: {command}"
    except Exception as e:
        logger.error(f"Web command failed: {e}")
        return f"Error executing command: {e}"


def start_web_server():
    """Start the Flask web server in a background thread."""
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    web_app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
