"""Post-download completion watcher.

After an enqueue, polls chapter download state; when everything lands,
triggers a Komga scan and notifies the channel. Fire-and-forget task —
a bot restart orphans it, in which case Komga's 6h scheduled scan is
the backstop (documented trade-off: no persistence layer in MVP).
"""
from __future__ import annotations

import asyncio
import logging

import discord

from .komga import KomgaClient
from .suwayomi import SuwayomiClient

log = logging.getLogger("manga-bot.watcher")

# Hold strong refs — asyncio only keeps weak refs to tasks; without this,
# a long-running watcher can be garbage-collected mid-flight.
_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def watch_downloads_then_scan(
    suwayomi: SuwayomiClient,
    komga: KomgaClient,
    channel: discord.abc.Messageable,
    title: str,
    chapter_ids: list[int],
    poll_seconds: int = 30,
    max_minutes: int = 120,
) -> None:
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_minutes * 60
        total = len(chapter_ids)

        while loop.time() < deadline:
            await asyncio.sleep(poll_seconds)
            chapters = await suwayomi.chapters_status(chapter_ids)
            done = sum(c.isDownloaded for c in chapters)
            log.info("watcher[%s]: %d/%d downloaded", title, done, total)
            if done == total:
                ok = await komga.trigger_scan()
                await channel.send(
                    f"📚 **{title}** — all {total} chapters downloaded. "
                    + ("Komga scan triggered — ready to read."
                       if ok else "Komga scan failed; it'll appear on the next scheduled scan.")
                )
                return

        # Timed out: report partial state, scan anyway for what landed
        chapters = await suwayomi.chapters_status(chapter_ids)
        done = sum(c.isDownloaded for c in chapters)
        await komga.trigger_scan()
        await channel.send(
            f"⏱️ **{title}** — {done}/{total} chapters downloaded after "
            f"{max_minutes} min; scan triggered for what's available. "
            "The rest will appear via scheduled scans."
        )
    except Exception:
        log.exception("watcher[%s] crashed", title)
