"""
Logging setup for Cortana Bot.

Import `logger` from this module wherever logging is needed:

    from logger_setup import logger
    logger.info("...")

Configuring the logger here (instead of in main.py) means every module can
import it directly without worrying about import order.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

import config

# The AI's replies can contain characters Windows' default console/file
# encoding (cp1252) can't represent — curly quotes, en/em/non-breaking
# dashes, emoji, accented letters. Without this, logging.info() on such a
# line throws UnicodeEncodeError deep inside the logging module, which
# prints an ugly "--- Logging error ---" traceback (and on the file
# handler, silently drops that log line) every time the model uses one.
#
# Force UTF-8 on stdout/stderr where possible (Python 3.7+), and always
# write the log file as UTF-8 — falling back to '?' for anything that
# still can't be displayed rather than crashing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass  # not a real console (e.g. redirected/piped) — safe to skip

file_handler = RotatingFileHandler(
    config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5,
    encoding='utf-8', errors='replace'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logger = logging.getLogger('CortanaBot')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
