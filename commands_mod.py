"""
Moderator+ chat commands for Project Reclaimer: bot on/off, moderation
(kick/ban/tempban/unban/warn/mute) and player stats lookups.

Map/mode/team/vote control (maps, modes, map, mode, load, nextmap,
teamcount, shuffle, startvote, passvote, cancelvote) lives in
commands_game.py and is dispatched from here; servername/password are
owner-only and dispatched from commands_admin.py.

Still absent from the original ElDewrito-era cortana_bot because Reclaimer
has no RCON equivalent: bot-driven map rotation (rotation/shufflerotation),
shouldannounce, reloadvoting and the voting* settings — votes are run with
startvote/passvote/cancelvote instead.
"""

import config
import state
import rcon
import auth
import tts
import warnings_store
import bans
import moderation_actions
import moderators
import server_info
import player_stats
import ai_providers
import commands_game


def handle(player_name: str, player_uid: str, cmd: str, args: list, mod_or_owner: bool):
    """Dispatch one of config.MOD_CMDS. Caller has already checked cmd is in that set."""
    if not mod_or_owner:
        rcon.send_chat(f"@{player_name}: You don't have permission for that.")
        return

    if cmd in config.GAME_CMDS:
        commands_game.handle(player_name, player_uid, cmd, args)
        return

    if cmd == "on":
        state.bot_enabled = True
        rcon.send_chat("Online.")

    elif cmd == "off":
        state.bot_enabled = False
        rcon.send_chat("Going offline.")

    elif cmd == "status":
        mods = moderators.load_mods()
        rcon.send_chat(
            f"Status: {'On' if state.bot_enabled else 'Off'} | "
            f"Cooldown: {state.PLAYER_COOLDOWN}s | "
            f"Provider: {ai_providers.get_active_provider_name()} | "
            f"LoadBalance: {'on' if state.load_balancing_enabled else 'off'} | "
            f"AutoMod: {'on' if state.automod_enabled else 'off'} | "
            f"AFK: {'on' if state.afk_enabled else 'off'} | "
            f"Callouts: {'on' if state.callouts_enabled else 'off'} | "
            f"Discord: {'on' if state.discord_enabled else 'off'} | "
            f"Mods: {len(mods)}"
        )

    elif cmd == "clear":
        state.player_last_ask.clear()
        rcon.send_chat("All cooldowns cleared.")

    elif cmd == "cooldown" and args:
        try:
            state.PLAYER_COOLDOWN = int(args[0])
            rcon.send_chat(f"Cooldown set to {state.PLAYER_COOLDOWN}s.")
        except ValueError:
            rcon.send_chat("Usage: !ai cooldown <seconds>")

    elif cmd == "automod" and args:
        state.automod_enabled = args[0].lower() == "on"
        rcon.send_chat(f"Auto-moderation {'enabled' if state.automod_enabled else 'disabled'}.")

    elif cmd == "provider" and args:
        provider = args[0].lower()
        valid = [n for n, _, _ in ai_providers.CLOUD_PROVIDER_CHAIN] + ["auto"]
        if provider in valid:
            state.active_provider = provider
            rcon.send_chat(f"Provider set to {provider.capitalize()}.")
        else:
            rcon.send_chat(f"Options: {', '.join(valid)}")

    elif cmd == "loadbalance" and args:
        if args[0].lower() == "on":
            state.load_balancing_enabled = True
            rcon.send_chat("Load balancing enabled. API providers will cycle on failures.")
        elif args[0].lower() == "off":
            state.load_balancing_enabled = False
            rcon.send_chat("Load balancing disabled. Sticking with first available provider.")
        else:
            rcon.send_chat("Usage: !ai loadbalance on/off")

    elif cmd == "say" and args:
        message = " ".join(args)
        tts.speak_to_game(message)
        rcon.send_chat(f"Speaking: {message}")

    elif cmd == "announce" and args:
        state.announce_enabled = args[0].lower() == "on"
        rcon.send_chat(f"Scheduled announcements {'enabled' if state.announce_enabled else 'disabled'}.")

    elif cmd == "afk" and args:
        state.afk_enabled = args[0].lower() == "on"
        msg = f"AFK detection {'enabled' if state.afk_enabled else 'disabled'}."
        if state.afk_enabled and config.AFK_TIMEOUT_MINUTES == 0:
            msg += " Set AFK_TIMEOUT_MINUTES in the script to activate."
        rcon.send_chat(msg)

    elif cmd == "callouts" and args:
        state.callouts_enabled = args[0].lower() == "on"
        msg = f"Proactive callouts {'enabled' if state.callouts_enabled else 'disabled'}."
        if state.callouts_enabled:
            msg += " (Betrayals, suicides and lead changes only — no down/kill-feed callouts yet.)"
        rcon.send_chat(msg)

    elif cmd == "kick" and args:
        target_name, _ = server_info.get_target_name(args)
        moderation_actions.do_kick(player_name, player_uid, target_name)

    elif cmd == "ban" and args:
        target_name, _ = server_info.get_target_name(args)
        moderation_actions.do_ban(player_name, player_uid, target_name)

    elif cmd == "tempban" and args:
        try:
            duration = int(args[-1])
            name_args = args[:-1]
        except ValueError:
            duration = 5
            name_args = args
        if not name_args:
            rcon.send_chat("Usage: !ai tempban <name> [minutes]")
            return
        target_name, _ = server_info.get_target_name(name_args)
        moderation_actions.do_tempban(player_name, player_uid, target_name, duration)

    elif cmd == "unban" and args:
        # Reclaimer's unban takes a player ID, IP, or range -- NOT a name
        # (the banned player isn't connected for the server to resolve a
        # name against). Take the raw argument as-is rather than trying
        # get_target_name()'s connected-player name matching.
        identifier = " ".join(args)
        if bans.remove_ban(identifier, moderator=player_name):
            rcon.send_chat(f"Unbanned {identifier}.")
        else:
            rcon.send_chat(f"Couldn't unban '{identifier}' — check the ID/IP with !ai banlist.")

    elif cmd == "banlist":
        active = bans.get_active_bans()
        if not active:
            rcon.send_chat("No active bans.")
        else:
            rcon.send_chat(f"Active bans ({len(active)}):")
            for ban in active[:5]:
                exp = ban.get("expires_at") or "permanent"
                rcon.send_chat(f"  {ban.get('name')} ({ban.get('uid', '?')}) — {exp}")

    elif cmd == "warn" and len(args) >= 2:
        target_name, reason_start = server_info.get_target_name(args)
        reason = " ".join(args[reason_start:])
        if not reason:
            rcon.send_chat(f"@{player_name}: Please provide a reason for the warning.")
            return
        target_info = server_info.get_player_info(target_name)
        target_uid = target_info.get("uid", "")
        if target_uid and auth.is_protected(target_uid):
            rcon.send_chat("I won't act against the server administrator.")
            return
        if not auth.is_owner(player_uid) and target_uid and moderators.is_mod(target_uid):
            rcon.send_chat(f"@{player_name}: Moderators cannot warn other moderators.")
            return
        count = warnings_store.add_warning(target_name, target_uid, f"{reason} (warned by {player_name})", moderator=player_name)
        remaining = max(0, config.WARN_KICK_THRESHOLD - count)
        if count < config.WARN_KICK_THRESHOLD:
            rcon.send_chat(f"@{target_name}: Warning {count}/{config.WARN_KICK_THRESHOLD} — {reason}. {remaining} left before action.")
        elif count == config.WARN_KICK_THRESHOLD:
            rcon.send_chat(f"{target_name} has been kicked after {count} warnings.")
            rcon.send_command(f"kick {rcon.quote_if_needed(target_name)}")

    elif cmd == "warnings" and args:
        target_name, _ = server_info.get_target_name(args)
        target_info = server_info.get_player_info(target_name)
        target_uid = target_info.get("uid", "")
        data = warnings_store.get_warnings(target_name, target_uid)
        rcon.send_chat(f"{target_name} has {data.get('count', 0)} warning(s).")

    elif cmd == "clearwarnings" and args:
        target_name, _ = server_info.get_target_name(args)
        if warnings_store.clear_warnings(target_name):
            rcon.send_chat(f"Warnings cleared for {target_name}.")
        else:
            rcon.send_chat(f"No warnings found for '{target_name}'.")

    elif cmd == "mute" and args:
        target_name, _ = server_info.get_target_name(args)
        target_info = server_info.get_player_info(target_name)
        target_uid = target_info.get("uid", "")
        if target_uid and auth.is_protected(target_uid):
            rcon.send_chat("I won't act against the server administrator.")
            return
        rcon.send_command(f"mute {rcon.quote_if_needed(target_name)}")
        rcon.send_chat(f"{target_name} has been muted.")

    elif cmd == "unmute" and args:
        target_name, _ = server_info.get_target_name(args)
        rcon.send_command(f"unmute {rcon.quote_if_needed(target_name)}")
        rcon.send_chat(f"{target_name} has been unmuted.")

    elif cmd == "tell" and len(args) >= 2:
        target_name, msg_start = server_info.get_target_name(args)
        message = " ".join(args[msg_start:])
        rcon.send_command(f"tell {rcon.quote_if_needed(target_name)} {message}")
        rcon.send_chat(f"Message sent to {target_name}.")

    elif cmd == "stats":
        if args:
            target_name = " ".join(args)
            data = player_stats.get_player_stats(target_name)
            rcon.send_chat(player_stats.format_stats(data))
        else:
            data = player_stats.get_player_stats(player_name, player_uid)
            rcon.send_chat(f"@{player_name}: {player_stats.format_stats(data)}")

    else:
        rcon.send_chat(
            "Commands: on/off/status/clear/cooldown/automod | "
            "tell/kick/ban/tempban/unban/banlist | "
            "warn/warnings/clearwarnings | mute/unmute | stats | "
            "maps/modes/map/mode/load/nextmap | teamcount/shuffle | "
            "startvote/passvote/cancelvote"
        )
