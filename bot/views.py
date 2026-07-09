"""Discord UI: search select, admin confirm, and restart-surviving approval cards.

Approval buttons are DynamicItems: state lives in the custom_id
(manga:approve:<manga_id>:<requester_id>), re-hydrated by regex on any
interaction — pending approvals survive bot restarts with no database.
Chapter ids are deliberately NOT stored: per the v2.3.2238 contract they are
per-instance DB ids, so Approve re-fetches fresh.
"""
from __future__ import annotations

import re

import discord

from .config import Settings
from .komga import KomgaClient
from .suwayomi import Chapter, MangaResult, SuwayomiClient
from .watcher import spawn, watch_downloads_then_scan


def _clients(interaction: discord.Interaction) -> tuple[SuwayomiClient, KomgaClient, Settings]:
    bot = interaction.client  # MangaBot — carries the shared clients
    return bot.suwayomi, bot.komga, bot.settings  # type: ignore[attr-defined]


class ApproveButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"manga:approve:(?P<manga_id>\d+):(?P<requester_id>\d+)",
):
    def __init__(self, manga_id: int, requester_id: int):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                custom_id=f"manga:approve:{manga_id}:{requester_id}",
            )
        )
        self.manga_id = manga_id
        self.requester_id = requester_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["manga_id"]), int(match["requester_id"]))

    async def callback(self, interaction: discord.Interaction):
        suwayomi, komga, settings = _clients(interaction)
        if interaction.user.id != settings.admin_user_id:
            await interaction.response.send_message(
                "Only the admin can approve requests.", ephemeral=True
            )
            return

        await interaction.response.defer()
        title = await suwayomi.add_to_library(self.manga_id)
        chapters = await suwayomi.fetch_chapters(self.manga_id)  # fresh ids, always
        ids = [c.id for c in chapters if not c.isDownloaded]
        await suwayomi.enqueue_downloads(ids)

        await interaction.edit_original_response(
            content=(
                f"✅ **{title}** approved — {len(ids)} chapters queued. "
                f"<@{self.requester_id}> will be pinged when it's ready."
            ),
            embed=None,
            view=None,
        )
        spawn(
            watch_downloads_then_scan(
                suwayomi, komga, interaction.channel,
                title, ids, mention=f"<@{self.requester_id}>",
            )
        )


class DenyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"manga:deny:(?P<manga_id>\d+):(?P<requester_id>\d+)",
):
    def __init__(self, manga_id: int, requester_id: int):
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.danger,
                custom_id=f"manga:deny:{manga_id}:{requester_id}",
            )
        )
        self.manga_id = manga_id
        self.requester_id = requester_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["manga_id"]), int(match["requester_id"]))

    async def callback(self, interaction: discord.Interaction):
        _, _, settings = _clients(interaction)
        if interaction.user.id != settings.admin_user_id:
            await interaction.response.send_message(
                "Only the admin can deny requests.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content=f"❌ Request denied. <@{self.requester_id}>", embed=None, view=None
        )


def approval_view(manga_id: int, requester_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)  # persistent — buttons re-match by custom_id
    view.add_item(ApproveButton(manga_id, requester_id))
    view.add_item(DenyButton(manga_id, requester_id))
    return view


class ResultSelect(discord.ui.Select):
    def __init__(self, results: list[MangaResult]):
        options = []
        for m in results[:25]:
            badge = " · in library" if m.inLibrary else ""
            options.append(
                discord.SelectOption(
                    label=m.title[:100],
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
        chapters = await view.suwayomi.fetch_chapters(manga.id)
        view.stop()
        n = len(chapters)

        is_admin = interaction.user.id == view.settings.admin_user_id
        if is_admin and not view.settings.force_approval:
            confirm = ConfirmView(view.suwayomi, view.komga, view.settings, manga, chapters)
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
            return

        # Non-admin (or forced): post an approval card
        embed = discord.Embed(title=manga.title, color=discord.Color.blurple())
        embed.add_field(name="Source", value=manga.source_name, inline=True)
        embed.add_field(name="Chapters", value=str(n), inline=True)
        embed.add_field(name="Requested by", value=interaction.user.mention, inline=True)
        await interaction.edit_original_response(
            content=f"📥 Request pending approval — <@{view.settings.admin_user_id}>",
            embed=embed,
            view=approval_view(manga.id, interaction.user.id),
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
                self.suwayomi, self.komga, interaction.channel,
                self.manga.title, ids,
            )
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)
