"""Admin-only chat commands: mod roster management, backups, the Discord toggle, and server name/join password."""

import os

import config
import state
import rcon
import auth
import moderators
import backup_manager
import server_info
import commands_game
from logger_setup import logger


def handle(player_name: str, player_uid: str, cmd: str, args: list):
    """Dispatch one of config.ADMIN_ONLY_CMDS. Caller has already checked cmd is in that set."""
    if not auth.is_owner(player_uid):
        rcon.send_chat(f"@{player_name}: That command is restricted to the server owner.")
        return

    if cmd in config.GAME_ADMIN_CMDS:
        commands_game.handle_admin(player_name, player_uid, cmd, args)
        return

    if cmd == "addmod" and args:
        target_name, _ = server_info.get_target_name(args)
        target_info = server_info.get_player_info(target_name)
        target_uid = target_info.get("uid", "")
        if not target_uid:
            rcon.send_chat(f"Player '{target_name}' not found in server.")
            return
        if auth.is_owner(target_uid):
            rcon.send_chat("The server owner is already above moderator level.")
            return
        moderators.add_mod(target_name, target_uid)
        rcon.send_chat(f"{target_name} has been added as a moderator.")

    elif cmd == "removemod" and args:
        target_name, _ = server_info.get_target_name(args)
        if moderators.remove_mod(target_name):
            rcon.send_chat(f"{target_name} is no longer a moderator.")
        else:
            rcon.send_chat(f"'{target_name}' is not a moderator.")

    elif cmd == "backup":
        try:
            backup_folder = backup_manager.create_backup()
            rcon.send_chat(f"Backup created successfully: {os.path.basename(backup_folder)}")
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            rcon.send_chat(f"Backup failed: {e}")

    elif cmd == "backuplist":
        backups = backup_manager.get_backup_list()
        if not backups:
            rcon.send_chat("No backups found.")
        else:
            backup_names = [f"{b[1]} ({b[0].strftime('%Y-%m-%d %H:%M:%S')})" for b in backups[:10]]
            rcon.send_chat(f"Recent backups: {', '.join(backup_names[:5])}")
            if len(backup_names) > 5:
                rcon.send_chat(f"Total {len(backups)} backups. Use !ai restore <name> to restore.")

    elif cmd == "restore" and args:
        backup_name = args[0]
        backup_name = backup_name.strip('"').strip("'")
        backup_path = os.path.join(config.BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            rcon.send_chat(f"Backup '{backup_name}' not found. Use !ai backuplist to see available backups.")
            return
        rcon.send_chat(f"Restoring from backup '{backup_name}'... This may take a moment.")
        if backup_manager.restore_backup(backup_name):
            rcon.send_chat(f"Restored from backup '{backup_name}'. Some changes may require a restart to take effect.")
            logger.info(f"Restored from backup by {player_name}")
        else:
            rcon.send_chat(f"Failed to restore from backup '{backup_name}'.")

    elif cmd == "discord" and args:
        state.discord_enabled = args[0].lower() == "on"
        rcon.send_chat(f"Discord bridge {'enabled' if state.discord_enabled else 'disabled'}.")
