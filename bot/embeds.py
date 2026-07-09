"""Shared embed builders.

build_embed        — details card (big image): request flow + #admin-requests
build_update_embed — Seerr-style notification (right thumbnail): #request-updates
build_added_embed  — library showcase card (gold, big image, footer): #manga-added
Covers are LAN-fetched bytes re-uploaded per message: discord.File streams are
single-use, so a fresh File is built from bytes on every send.
"""
from __future__ import annotations

import io

import discord

from .suwayomi import MangaDetails


def _truncate(text: str | None, limit: int = 300) -> str:
    desc = (text or "").strip()
    if len(desc) > limit:
        desc = desc[:limit].rsplit(" ", 1)[0] + "…"
    return desc


def _cover_files(cover: bytes | None) -> list[discord.File]:
    if not cover:
        return []
    return [discord.File(io.BytesIO(cover), filename="cover.png")]


def build_embed(
    details: MangaDetails,
    source_name: str,
    n_chapters: int,
    cover: bytes | None,
    requester: discord.abc.User | None = None,
) -> tuple[discord.Embed, list[discord.File]]:
    embed = discord.Embed(
        title=details.title,
        description=_truncate(details.description) or None,
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Source", value=source_name, inline=True)
    embed.add_field(name="Chapters", value=str(n_chapters), inline=True)
    if details.status:
        embed.add_field(name="Status", value=details.status.title(), inline=True)
    if details.author:
        embed.add_field(name="Author", value=details.author, inline=False)
    if requester is not None:
        embed.add_field(name="Requested by", value=requester.mention, inline=False)
    files = _cover_files(cover)
    if files:
        embed.set_image(url="attachment://cover.png")
    return embed, files


def build_update_embed(
    title: str,
    description: str | None,
    requester_name: str,
    n_chapters: int | str,
    approved: bool,
    thumbnail: bytes | str | None = None,
) -> tuple[discord.Embed, list[discord.File]]:
    """Seerr-notification style for #request-updates.
    thumbnail: raw bytes (approve path) or an existing CDN url str (deny path)."""
    action = "Approved" if approved else "Denied"
    embed = discord.Embed(
        title=f"Manga Request {action}: {title}",
        description=_truncate(description) or None,
        color=discord.Color.green() if approved else discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Requested By", value=requester_name, inline=True)
    embed.add_field(
        name="Request Status", value="Processing" if approved else "Denied", inline=True
    )
    embed.add_field(name="Chapters", value=str(n_chapters), inline=True)
    files: list[discord.File] = []
    if isinstance(thumbnail, bytes):
        files = _cover_files(thumbnail)
        embed.set_thumbnail(url="attachment://cover.png")
    elif isinstance(thumbnail, str):
        embed.set_thumbnail(url=thumbnail)
    return embed, files


def build_added_embed(
    details: MangaDetails,
    source_name: str,
    n_downloaded: int,
    n_total: int,
    cover: bytes | None,
) -> tuple[discord.Embed, list[discord.File]]:
    """Library showcase card for #manga-added — gold, big art, self-contained."""
    complete = n_downloaded == n_total
    embed = discord.Embed(
        title=f"📚 Ready to Read: {details.title}",
        description=_truncate(details.description) or None,
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Chapters",
        value=str(n_total) if complete else f"{n_downloaded}/{n_total}",
        inline=True,
    )
    embed.add_field(name="Source", value=source_name, inline=True)
    if details.status:
        embed.add_field(name="Series Status", value=details.status.title(), inline=True)
    if details.author:
        embed.add_field(name="Author", value=details.author, inline=False)
    embed.set_footer(text="Now available in Komga")
    files = _cover_files(cover)
    if files:
        embed.set_image(url="attachment://cover.png")
    return embed, files
