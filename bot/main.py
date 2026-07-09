"""Entrypoint. Guild-scoped sync; dynamic approval buttons registered in setup_hook."""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from .commands import MangaCommands
from .config import load_settings
from .komga import KomgaClient
from .suwayomi import SuwayomiClient
from .views import ApproveButton, DenyButton

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("manga-bot")


class MangaBot(discord.Client):
    """Carries shared clients so restart-hydrated views can reach them."""

    def __init__(self, settings):
        super().__init__(intents=discord.Intents.default())
        self.settings = settings
        self.suwayomi = SuwayomiClient(settings.suwayomi_url)
        self.komga = KomgaClient(
            settings.komga_url, settings.komga_api_key, settings.komga_library_id
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # DynamicItems match pending approval cards from before any restart
        self.add_dynamic_items(ApproveButton, DenyButton)

    async def on_ready(self) -> None:
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info(
            "Logged in as %s — synced %d command group(s), force_approval=%s",
            self.user, len(synced), self.settings.force_approval,
        )


def main() -> None:
    settings = load_settings()
    client = MangaBot(settings)
    client.tree.add_command(MangaCommands(client.suwayomi, client.komga, settings))
    client.run(settings.discord_token)


if __name__ == "__main__":
    main()
