"""Entrypoint. Guild-scoped command sync — commands appear instantly, no global propagation wait."""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from .commands import MangaCommands
from .config import load_settings
from .komga import KomgaClient
from .suwayomi import SuwayomiClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("manga-bot")


def main() -> None:
    settings = load_settings()
    # No privileged intents needed: interactions arrive regardless of intents
    client = discord.Client(intents=discord.Intents.default())
    tree = app_commands.CommandTree(client)

    suwayomi = SuwayomiClient(settings.suwayomi_url)
    komga = KomgaClient(settings.komga_url, settings.komga_api_key, settings.komga_library_id)
    tree.add_command(MangaCommands(suwayomi, komga, settings))

    @client.event
    async def on_ready() -> None:
        guild = discord.Object(id=settings.guild_id)
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        log.info("Logged in as %s — synced %d command group(s)", client.user, len(synced))

    client.run(settings.discord_token)


if __name__ == "__main__":
    main()
