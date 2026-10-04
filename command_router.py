"""
Chat command entry point: parses `!ai <command> ...`, works out the
player's permission level, and routes to the right handler module.
"""

import config
import rcon
import auth
import commands_misc
import commands_admin
import commands_mod


def handle_command(player_name: str, player_uid: str, player_ip: str, command: str):
    parts = command.strip().split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]

    owner = auth.is_owner(player_uid)
    mod_or_owner = auth.is_mod_or_owner(player_uid)

    # ── Debug ──
    if cmd == "debugall":
        commands_misc.cmd_debugall(player_name, player_uid, owner)
        return

    # ── Direct handlers (checked before the admin/mod tables) ──
    if cmd == "reload":
        commands_misc.cmd_reload(player_name, mod_or_owner)
        return

    if cmd == "forget":
        commands_misc.cmd_forget(player_name, mod_or_owner)
        return

    if cmd == "memory" and args:
        commands_misc.cmd_memory(player_name, mod_or_owner, args)
        return

    if cmd == "voice" and args:
        commands_misc.cmd_voice(player_name, mod_or_owner, args)
        return

    if cmd == "local" and args:
        commands_misc.cmd_local(player_name, mod_or_owner, args)
        return

    if cmd == "modlist":
        commands_misc.cmd_modlist(player_name, mod_or_owner)
        return

    if cmd == "gamestatus":
        commands_misc.cmd_gamestatus()
        return

    if cmd == "mystats":
        commands_misc.cmd_mystats(player_name, player_uid)
        return

    # ── Admin-only commands ──
    if cmd in config.ADMIN_ONLY_CMDS:
        commands_admin.handle(player_name, player_uid, cmd, args)
        return

    # ── Mod + admin commands ──
    if cmd in config.MOD_CMDS:
        commands_mod.handle(player_name, player_uid, cmd, args, mod_or_owner)
        return

    rcon.send_chat(
        "Admin only: addmod/removemod/backup/restore/backuplist/discord/servername/password | "
        "For help, ask a moderator."
    )
