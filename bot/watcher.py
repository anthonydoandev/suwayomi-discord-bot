"""Post-download completion watcher.

Polls chapter download state after enqueue; on completion triggers a Komga
scan (silently — failures are logged, not posted) and posts the library
showcase card to #manga-added. Fire-and-forget — a restart orphans it;
Komga's 6h scheduled scan is the backstop.
"""
from __future__ import annotations

import asyncio
import logging

import discord

from .embeds import build_added_embed
from .komga import KomgaClient
from .suwayomi import MangaDetails, SuwayomiClient

log = logging.getLogger("manga-bot.watcher")

# asyncio holds only weak refs to tasks — keep strong refs or risk mid-flight GC
_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def watch_downloads_then_scan(
    suwayomi: SuwayomiClient,
    komga: KomgaClient,
    channel: discord.abc.Messageable,
    details: MangaDetails,
    source_name: str,
    cover: bytes | None,
    chapter_ids: list[int],
    poll_seconds: int = 30,
    max_minutes: int = 120,
) -> None:
    title = details.title
    total = len(chapter_ids)
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_minutes * 60

        done = 0
        while loop.time() < deadline:
            await asyncio.sleep(poll_seconds)
            chapters = await suwayomi.chapters_status(chapter_ids)
            done = sum(c.isDownloaded for c in chapters)
            log.info("watcher[%s]: %d/%d downloaded", title, done, total)
            if done == total:
                break

        if not await komga.trigger_scan():
            log.warning("watcher[%s]: komga scan trigger failed", title)
        embed, files = build_added_embed(details, source_name, done, total, cover)
        await channel.send(embed=embed, files=files)
    except Exception:
        log.exception("watcher[%s] crashed", title)
