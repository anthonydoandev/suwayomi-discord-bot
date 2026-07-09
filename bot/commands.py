"""Slash commands: /manga request, /manga status, /manga scan — locked to #requests."""
from __future__ import annotations

import discord
from discord import app_commands

from .config import Settings
from .komga import KomgaClient
from .suwayomi import SuwayomiClient
from .views import SearchView


class MangaCommands(app_commands.Group):
    def __init__(self, suwayomi: SuwayomiClient, komga: KomgaClient, settings: Settings):
        super().__init__(name="manga", description="Manga library requests")
        self.suwayomi = suwayomi
        self.komga = komga
        self.settings = settings
        self._source_names: dict[str, str] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != self.settings.requests_channel_id:
            await interaction.response.send_message(
                f"Manga commands live in <#{self.settings.requests_channel_id}>.",
                ephemeral=True,
            )
            return False
        return True

    async def _sources(self) -> dict[str, str]:
        if not self._source_names:
            all_sources = {s.id: s.displayName for s in await self.suwayomi.sources()}
            self._source_names = {
                sid: all_sources.get(sid, sid) for sid in self.settings.source_ids
            }
        return self._source_names

    @app_commands.command(name="request", description="Search for a manga and request it")
    @app_commands.describe(title="Manga title to search for")
    async def request(self, interaction: discord.Interaction, title: str):
        await interaction.response.defer()
        results = await self.suwayomi.search_all(await self._sources(), title)
        if not results:
            await interaction.followup.send(f"No results for **{title}**.")
            return
        view = SearchView(self.suwayomi, self.komga, self.settings, results)
        await interaction.followup.send(
            f"Results for **{title}** ({len(results)}):", view=view
        )

    @app_commands.command(name="status", description="Show the download queue")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        st = await self.suwayomi.download_status()
        if not st.queue:
            await interaction.followup.send("Download queue is empty — all caught up.")
            return
        lines = [
            f"• {q.name} — {q.progress:.0%} ({q.state.lower()})" for q in st.queue[:15]
        ]
        more = f"\n…and {len(st.queue) - 15} more" if len(st.queue) > 15 else ""
        await interaction.followup.send(
            f"**Downloader: {st.state}** — {len(st.queue)} queued\n" + "\n".join(lines) + more
        )

    @app_commands.command(name="scan", description="Trigger a Komga library scan (admin)")
    async def scan(self, interaction: discord.Interaction):
        if interaction.user.id != self.settings.admin_user_id:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        ok = await self.komga.trigger_scan()
        await interaction.followup.send(
            "Komga scan started." if ok else "Komga scan failed — check the API key."
        )
