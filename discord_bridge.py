"""Discord bridge: game chat <-> Discord, via a webhook (game->Discord) and a bot (Discord->game)."""

import asyncio
import threading

import requests

import rcon
import state
from logger_setup import logger


def send_to_discord(player_name: str, message: str):
    """Send a game chat message to Discord via webhook (game -> Discord)."""
    if not state.discord_enabled or not state.DISCORD_WEBHOOK_URL:
        return
    try:
        payload = {
            "username": f"[ElDewrito] {player_name}",
            "content": message,
            "avatar_url": "https://i.imgur.com/4M34hi2.png"
        }
        requests.post(state.DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        logger.info(f"[DISCORD] Webhook failed: {e}")


def start_discord_bot():
    """Start the Discord bot that reads Discord messages and forwards to game (Discord -> game)."""
    if not state.DISCORD_BOT_TOKEN or not state.DISCORD_CHANNEL_ID:
        logger.info("[DISCORD] Bot token or channel ID not set — Discord -> game bridge disabled.")
        return

    try:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            logger.info(f"[DISCORD] Bot connected as {client.user}")

        @client.event
        async def on_message(message):
            if message.author.bot:
                return
            if str(message.channel.id) != str(state.DISCORD_CHANNEL_ID):
                return
            if not state.discord_enabled:
                return
            content = message.content
            author = message.author.display_name
            if len(content) > 150:
                content = content[:147] + "..."
            rcon.send_chat(f"[Discord] {author}: {content}")

        def run_bot():
            asyncio.run(client.start(state.DISCORD_BOT_TOKEN))

        threading.Thread(target=run_bot, daemon=True).start()

    except ImportError:
        logger.info("[DISCORD] discord.py not installed. Run: pip install discord.py")
    except Exception as e:
        logger.info(f"[DISCORD] Bot failed to start: {e}")
