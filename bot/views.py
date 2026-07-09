"""Discord UI: search select, details card, admin confirm, friend request flow.

Channel routing:
  #requests        — command invocations, details card, Request button
  #admin-requests  — friend approval cards (DynamicItem, restart-surviving);
                     admin requests auto-approve and skip this channel
  #request-updates — Seerr-style approved/denied notifications (no pings)
  #manga-added     — download-complete cards (no pings)

Chapter ids are never persisted in custom_ids (per-instance DB ids) —
Approve always re-fetches. Deny recycles data from the admin card embed
(title, description, chapter count, CDN cover url) — zero source traffic.
Independent source fetches run under asyncio.gather — the user waits for
the slowest call, not the sum.
"""
from __future__ import annotations

import asyncio
import re

import discord

from .config import Settings
from .embeds import build_embed, build_update_embed
from .komga import KomgaClient
from .suwayomi import Chapter, MangaDetails, MangaResult, SuwayomiClient
from .watcher import spawn, watch_downloads_then_scan


def _clients(interaction: discord.Interaction) -> tuple[SuwayomiClient, KomgaClient, Settings]:
    bot = interaction.client
    return bot.suwayomi, bot.komga, bot.settings  # type: ignore[attr-defined]


async def _channel(client: discord.Client, channel_id: int) -> discord.abc.Messageable:
    return client.get_channel(channel_id) or await client.fetch_channel(channel_id)


async def _display_name(client: discord.Client, user_id: int) -> str:
    user = client.get_user(user_id)
    if user is None:
        try:
            user = await client.fetch_user(user_id)
        except discord.HTTPException:
            return "unknown"
    return user.display_name


def _card_field(message: discord.Message | None, name: str, default: str = "?") -> str:
    if message and message.embeds:
        for f in message.embeds[0].fields:
            if f.name == name and f.value:
                return f.value
    return default


# --------------------------- approval buttons -------------------------------


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
        # add/details/chapters are independent — gather; cover needs details' url
        title, details, chapters = await asyncio.gather(
            suwayomi.add_to_library(self.manga_id),
            suwayomi.fetch_manga_details(self.manga_id),
            suwayomi.fetch_chapters(self.manga_id),  # fresh ids, always
        )
        cover = await suwayomi.fetch_thumbnail(details.thumbnailUrl)
        ids = [c.id for c in chapters if not c.isDownloaded]
        await suwayomi.enqueue_downloads(ids)

        source_name = _card_field(interaction.message, "Source", "Unknown")

        await interaction.edit_original_response(
            content=f"✅ Approved — **{title}**, {len(ids)} chapters queued.",
            view=None,
        )

        requester_name = await _display_name(interaction.client, self.requester_id)
        embed, files = build_update_embed(
            title=details.title,
            description=details.description,
            requester_name=requester_name,
            n_chapters=len(chapters),
            approved=True,
            thumbnail=cover,
        )
        updates = await _channel(interaction.client, settings.request_updates_channel_id)
        await updates.send(embed=embed, files=files)

        added = await _channel(interaction.client, settings.manga_added_channel_id)
        spawn(
            watch_downloads_then_scan(
                suwayomi, komga, added, details, source_name, cover, ids,
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

        # Recycle everything from the admin card — no source round-trips on deny
        msg = interaction.message
        card = msg.embeds[0] if msg and msg.embeds else None
        title = card.title if card and card.title else "Request"
        description = card.description if card else None
        n_chapters = _card_field(msg, "Chapters")
        cover_url = card.image.url if card and card.image else None

        await interaction.response.edit_message(
            content=f"❌ Denied — **{title}**.", view=None
        )

        requester_name = await _display_name(interaction.client, self.requester_id)
        embed, files = build_update_embed(
            title=title,
            description=description,
            requester_name=requester_name,
            n_chapters=n_chapters,
            approved=False,
            thumbnail=cover_url,
        )
        updates = await _channel(interaction.client, settings.request_updates_channel_id)
        await updates.send(embed=embed, files=files)


def approval_view(manga_id: int, requester_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(ApproveButton(manga_id, requester_id))
    view.add_item(DenyButton(manga_id, requester_id))
    return view


# --------------------------- friend request flow ----------------------------


class RequestView(discord.ui.View):
    """Details card footer for non-admins: a single Request button."""

    def __init__(
        self,
        manga: MangaResult,
        details: MangaDetails,
        n_chapters: int,
        cover: bytes | None,
        requester_id: int,
    ):
        super().__init__(timeout=180)
        self.manga = manga
        self.details = details
        self.n_chapters = n_chapters
        self.cover = cover
        self.requester_id = requester_id

    @discord.ui.button(label="Request", style=discord.ButtonStyle.primary)
    async def request(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who searched can submit this request.", ephemeral=True
            )
            return
        _, _, settings = _clients(interaction)
        self.stop()

        await interaction.response.edit_message(content="📥 **Requested**", view=None)

        embed, files = build_embed(
            self.details, self.manga.source_name, self.n_chapters,
            self.cover, requester=interaction.user,
        )
        admin_ch = await _channel(interaction.client, settings.admin_requests_channel_id)
        await admin_ch.send(
            content="📥 New request",
            embed=embed,
            files=files,
            view=approval_view(self.manga.id, self.requester_id),
        )


# --------------------------- search + admin confirm -------------------------


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
        # Independent ops — run concurrently; thumbnail uses the search result's
        # url (identical to details.thumbnailUrl, verified in the API contract)
        details, chapters, cover = await asyncio.gather(
            view.suwayomi.fetch_manga_details(manga.id),
            view.suwayomi.fetch_chapters(manga.id),
            view.suwayomi.fetch_thumbnail(manga.thumbnailUrl),
        )
        view.stop()
        n = len(chapters)
        embed, files = build_embed(details, manga.source_name, n, cover)

        is_admin = interaction.user.id == view.settings.admin_user_id
        if is_admin and not view.settings.force_approval:
            gate = (
                f"⚠️ Large series: this will download **all {n} chapters**."
                if n > view.settings.bulk_confirm_threshold
                else ""
            )
            await interaction.edit_original_response(
                content=gate or None,
                embed=embed,
                attachments=files,
                view=ConfirmView(
                    view.suwayomi, view.komga, view.settings,
                    manga, details, cover, chapters,
                ),
            )
            return

        await interaction.edit_original_response(
            content="Press **Request** to submit for approval:",
            embed=embed,
            attachments=files,
            view=RequestView(manga, details, n, cover, interaction.user.id),
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
    """Admin path: same Request UX as friends, but auto-approved — no admin
    card; posts the approved notification directly to #request-updates."""

    def __init__(
        self,
        suwayomi: SuwayomiClient,
        komga: KomgaClient,
        settings: Settings,
        manga: MangaResult,
        details: MangaDetails,
        cover: bytes | None,
        chapters: list[Chapter],
    ):
        super().__init__(timeout=120)
        self.suwayomi = suwayomi
        self.komga = komga
        self.settings = settings
        self.manga = manga
        self.details = details
        self.cover = cover
        self.chapters = chapters

    @discord.ui.button(label="Request", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        self.stop()

        await self.suwayomi.add_to_library(self.manga.id)
        ids = [c.id for c in self.chapters if not c.isDownloaded]
        await self.suwayomi.enqueue_downloads(ids)

        await interaction.edit_original_response(
            content="📥 **Requested**", view=None
        )

        # Auto-approved: post the green notification card directly
        embed, files = build_update_embed(
            title=self.details.title,
            description=self.details.description,
            requester_name=interaction.user.display_name,
            n_chapters=len(self.chapters),
            approved=True,
            thumbnail=self.cover,
        )
        updates = await _channel(interaction.client, self.settings.request_updates_channel_id)
        await updates.send(embed=embed, files=files)

        added = await _channel(interaction.client, self.settings.manga_added_channel_id)
        spawn(
            watch_downloads_then_scan(
                self.suwayomi, self.komga, added,
                self.details, self.manga.source_name, self.cover, ids,
            )
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)
