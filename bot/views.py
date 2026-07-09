"""Discord UI components: search result selection + download confirmation."""
from __future__ import annotations

import discord

from .config import Settings
from .komga import KomgaClient
from .suwayomi import Chapter, MangaResult, SuwayomiClient
from .watcher import spawn, watch_downloads_then_scan


class ResultSelect(discord.ui.Select):
    def __init__(self, results: list[MangaResult]):
        options = []
        for m in results[:25]:  # Discord hard limit
            label = m.title[:100]
            badge = " · in library" if m.inLibrary else ""
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(m.id),
                    description=f"{m.source_name}{badge}"[:100],
                )
            )
        super().__init__(placeholder="Select a manga…", options=options)
        self._by_id = {m.id: m for m in results}

    async def callback(self, interaction: discord.Interaction):
        view: SearchView = self.view  # type: ignore[assignment]
        manga = self._by_id[int(self.values[0])]

        if manga.inLibrary:
            await interaction.response.edit_message(
                content=f"**{manga.title}** is already in the library — "
                "check Komga, new chapters download automatically.",
                embed=None,
                view=None,
            )
            return

        await interaction.response.defer()
        chapters = await view.suwayomi.fetch_chapters(manga.id)  # live scrape, seconds
        view.stop()

        confirm = ConfirmView(view.suwayomi, view.komga, view.settings, manga, chapters)
        n = len(chapters)
        gate = (
            f"\n⚠️ Large series: this will download **all {n} chapters**."
            if n > view.settings.bulk_confirm_threshold
            else ""
        )
        await interaction.edit_original_response(
            content=f"**{manga.title}** [{manga.source_name}] — {n} chapters found.{gate}",
            embed=None,
            view=confirm,
        )


class SearchView(discord.ui.View):
    def __init__(
        self,
        suwayomi: SuwayomiClient,
        komga: KomgaClient,
        settings: Settings,
        results: list[MangaResult],
    ):
        super().__init__(timeout=120)
        self.suwayomi = suwayomi
        self.komga = komga
        self.settings = settings
        self.add_item(ResultSelect(results))


class ConfirmView(discord.ui.View):
    def __init__(
        self,
        suwayomi: SuwayomiClient,
        komga: KomgaClient,
        settings: Settings,
        manga: MangaResult,
        chapters: list[Chapter],
    ):
        super().__init__(timeout=120)
        self.suwayomi = suwayomi
        self.komga = komga
        self.settings = settings
        self.manga = manga
        self.chapters = chapters

    @discord.ui.button(label="Download all", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

        await self.suwayomi.add_to_library(self.manga.id)
        ids = [c.id for c in self.chapters if not c.isDownloaded]
        await self.suwayomi.enqueue_downloads(ids)

        await interaction.edit_original_response(
            content=(
                f"✅ **{self.manga.title}** added — {len(ids)} chapters queued. "
                "I'll post here when it's ready to read."
            ),
            view=None,
        )
        spawn(
            watch_downloads_then_scan(
                self.suwayomi,
                self.komga,
                interaction.channel,
                self.manga.title,
                ids,
            )
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)
