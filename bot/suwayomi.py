"""Async GraphQL client for Suwayomi-Server.

Contract verified against v2.3.2238 (r2238, Stable) on 2026-07-09.
Operations live in graphql/*.graphql — this module executes them verbatim.
Schema findings encoded here:
  - fetchSourceManga, fetchChapters, fetchManga are mutations (live source scrapes)
  - enqueueChapterDownloads auto-starts the downloader; STOPPED = idle
  - startDownloader requires an empty input object
  - manga/chapter ids are per-instance DB ids: always fetch-then-enqueue
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from pydantic import BaseModel

_GQL_DIR = Path(__file__).resolve().parent.parent / "graphql"


def _op(name: str) -> str:
    return (_GQL_DIR / f"{name}.graphql").read_text()


class SuwayomiError(RuntimeError):
    """GraphQL-level errors (HTTP 200 with an errors array)."""


class Source(BaseModel):
    id: str
    displayName: str
    lang: str
    isNsfw: bool = False


class MangaResult(BaseModel):
    id: int
    title: str
    thumbnailUrl: str | None = None
    inLibrary: bool
    source_id: str = ""
    source_name: str = ""


class MangaDetails(BaseModel):
    id: int
    title: str
    description: str | None = None
    thumbnailUrl: str | None = None
    author: str | None = None
    status: str | None = None


class Chapter(BaseModel):
    id: int
    name: str
    sourceOrder: int = 0
    chapterNumber: float = 0.0
    isDownloaded: bool


class DownloadQueueItem(BaseModel):
    name: str
    progress: float
    state: str
    tries: int


class DownloadStatus(BaseModel):
    state: str  # STOPPED = idle when queue is empty — not an error
    queue: list[DownloadQueueItem]


class SuwayomiClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _gql(self, operation: str, variables: dict | None = None) -> dict:
        resp = await self._http.post(
            "/api/graphql",
            json={"query": _op(operation), "variables": variables or {}},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise SuwayomiError(str(payload["errors"]))
        return payload["data"]

    # -- sources ------------------------------------------------------------

    async def sources(self) -> list[Source]:
        data = await self._gql("sources")
        out = [Source(**n) for n in data["sources"]["nodes"]]
        return [s for s in out if s.id != "0"]  # drop Local source

    # -- search -------------------------------------------------------------

    async def search(self, source_id: str, query: str, page: int = 1) -> list[MangaResult]:
        data = await self._gql(
            "search", {"source": source_id, "query": query, "page": page}
        )
        return [
            MangaResult(**m, source_id=source_id)
            for m in data["fetchSourceManga"]["mangas"]
        ]

    async def search_all(
        self,
        sources: dict[str, str],
        query: str,
        per_source_limit: int = 8,
    ) -> list[MangaResult]:
        """Concurrent fan-out; a failing source degrades instead of sinking the search."""
        ids = list(sources)
        results = await asyncio.gather(
            *(self.search(sid, query) for sid in ids), return_exceptions=True
        )
        merged: list[MangaResult] = []
        for sid, res in zip(ids, results):
            if isinstance(res, BaseException):
                continue
            for m in res[:per_source_limit]:
                m.source_name = sources[sid]
                merged.append(m)
        return merged

    # -- library / details / chapters ----------------------------------------

    async def add_to_library(self, manga_id: int) -> str:
        data = await self._gql("add_to_library", {"id": manga_id})
        return data["updateManga"]["manga"]["title"]

    async def fetch_manga_details(self, manga_id: int) -> MangaDetails:
        data = await self._gql("fetch_manga_details", {"id": manga_id})
        return MangaDetails(**data["fetchManga"]["manga"])

    async def fetch_thumbnail(self, thumbnail_url: str | None) -> bytes | None:
        """Cover bytes over LAN — Discord's embed proxy can't reach VLAN 20, so
        covers are re-uploaded as attachments. Degrades to None on any failure."""
        if not thumbnail_url:
            return None
        try:
            resp = await self._http.get(thumbnail_url)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    async def fetch_chapters(self, manga_id: int) -> list[Chapter]:
        data = await self._gql("fetch_chapters", {"id": manga_id})
        chapters = [Chapter(**c) for c in data["fetchChapters"]["chapters"]]
        return sorted(chapters, key=lambda c: c.sourceOrder)

    # -- downloads ----------------------------------------------------------

    async def enqueue_downloads(
        self, chapter_ids: list[int], batch_size: int = 50
    ) -> None:
        """Batched enqueue — never one giant mutation."""
        for i in range(0, len(chapter_ids), batch_size):
            await self._gql("enqueue_downloads", {"ids": chapter_ids[i : i + batch_size]})
            await asyncio.sleep(0.5)

    async def download_status(self) -> DownloadStatus:
        data = await self._gql("download_status")
        raw = data["downloadStatus"]
        return DownloadStatus(
            state=raw["state"],
            queue=[
                DownloadQueueItem(
                    name=q["chapter"]["name"],
                    progress=q["progress"],
                    state=q["state"],
                    tries=q["tries"],
                )
                for q in raw["queue"]
            ],
        )

    async def start_downloader(self) -> str:
        data = await self._gql("start_downloader")
        return data["startDownloader"]["downloadStatus"]["state"]

    async def chapters_status(self, chapter_ids: list[int]) -> list[Chapter]:
        data = await self._gql("chapters_status", {"ids": chapter_ids})
        return [Chapter(**c) for c in data["chapters"]["nodes"]]
