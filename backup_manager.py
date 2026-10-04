"""
Backup system: periodic + on-demand snapshots of the bot's data files
(stats, bans, warnings, mods, memory, match history, rotation, config)
plus the logs directory, and a separate rolling zip of the bot's own
source code.
"""

import os
import shutil
import zipfile
from datetime import datetime

import config
from logger_setup import logger

# Keep the last 10 source-code backups (mirrors MAX_BACKUPS behaviour for
# the code snapshot, independent of the data-file backups below).
MAX_SCRIPT_BACKUPS = 10


def create_backup() -> str:
    """Create a timestamped backup of all important data files."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_folder = os.path.join(config.BACKUP_DIR, timestamp)
    os.makedirs(backup_folder, exist_ok=True)

    # Also snapshot the bot's own source code alongside the data backup.
    backup_script()

    backed_up = 0
    for filename in config.FILES_TO_BACKUP:
        src = os.path.join(config.BASE_DIR, filename)
        if os.path.exists(src):
            dst = os.path.join(backup_folder, filename)
            shutil.copy2(src, dst)
            backed_up += 1
            logger.debug(f"Backed up: {filename}")

    # Also back up the logs directory
    logs_dir = os.path.join(config.BASE_DIR, "logs")
    if os.path.exists(logs_dir):
        backup_logs = os.path.join(backup_folder, "logs")
        shutil.copytree(logs_dir, backup_logs)
        logger.debug("Backed up logs directory")

    cleanup_old_backups()

    logger.info(f"Backup created: {timestamp} ({backed_up} files)")
    return backup_folder


def cleanup_old_backups():
    """Delete old backups, keeping only the most recent MAX_BACKUPS."""
    if config.MAX_BACKUPS <= 0:
        return

    try:
        backups = []
        for folder in os.listdir(config.BACKUP_DIR):
            folder_path = os.path.join(config.BACKUP_DIR, folder)
            if os.path.isdir(folder_path):
                try:
                    timestamp = datetime.strptime(folder, "%Y-%m-%d_%H-%M-%S")
                    backups.append((timestamp, folder_path))
                except ValueError:
                    pass  # not a timestamped backup folder, skip it

        backups.sort(key=lambda x: x[0])

        to_delete = len(backups) - config.MAX_BACKUPS
        for i in range(to_delete):
            shutil.rmtree(backups[i][1])
            logger.info(f"Deleted old backup: {backups[i][0].strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        logger.error(f"Failed to cleanup old backups: {e}")


def get_backup_list() -> list:
    """Return list of available backups as (timestamp, folder_name), newest first."""
    backups = []
    for folder in os.listdir(config.BACKUP_DIR):
        folder_path = os.path.join(config.BACKUP_DIR, folder)
        if os.path.isdir(folder_path):
            try:
                timestamp = datetime.strptime(folder, "%Y-%m-%d_%H-%M-%S")
                backups.append((timestamp, folder))
            except ValueError:
                pass
    backups.sort(reverse=True)
    return backups


def backup_script():
    """Zip up the bot's own .py source files into a dated archive.

    The original single-file script copied itself (cortana_bot.py) to a
    timestamped filename. Now that the bot is a directory of modules,
    a zip of every .py file plays the same role.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    script_backup = os.path.join(config.BASE_DIR, f"cortana_bot_backup_{timestamp}.zip")

    py_files = [f for f in os.listdir(config.BASE_DIR) if f.endswith(".py")]
    with zipfile.ZipFile(script_backup, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in py_files:
            zf.write(os.path.join(config.BASE_DIR, filename), arcname=filename)
    logger.info(f"Script backup created: {script_backup}")

    # Clean up old script backups (keep last MAX_SCRIPT_BACKUPS)
    script_backups = sorted(
        (f for f in os.listdir(config.BASE_DIR)
         if f.startswith("cortana_bot_backup_") and f.endswith(".zip")),
        reverse=True
    )
    for old_backup in script_backups[MAX_SCRIPT_BACKUPS:]:
        os.remove(os.path.join(config.BASE_DIR, old_backup))
        logger.info(f"Deleted old script backup: {old_backup}")


def restore_backup(backup_name: str) -> bool:
    """Restore data files from a specific backup."""
    backup_path = os.path.join(config.BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        logger.error(f"Backup not found: {backup_name}")
        return False

    try:
        safety_backup = create_backup()
        logger.info(f"Created safety backup before restore: {safety_backup}")

        for filename in config.FILES_TO_BACKUP:
            src = os.path.join(backup_path, filename)
            dst = os.path.join(config.BASE_DIR, filename)
            if os.path.exists(src):
                shutil.copy2(src, dst)
                logger.info(f"Restored: {filename}")

        logger.info(f"Restored from backup: {backup_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        return False
