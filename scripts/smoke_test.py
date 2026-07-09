"""Live smoke test against LAN Suwayomi + Komga. Read-only ops.
Fixtures from Phase 1: manga 97 (Frieren), chapters 385/386 downloaded.
Run: python -m scripts.smoke_test
"""
import asyncio
import os

from dotenv import load_dotenv

from bot.komga import KomgaClient
from bot.suwayomi import SuwayomiClient

load_dotenv()

PASS = "\033[92m✓\033[0m"


async def main() -> None:
    s = SuwayomiClient(os.environ["SUWAYOMI_URL"])
    try:
        sources = await s.sources()
        assert sources and all(x.id != "0" for x in sources)
        print(f"{PASS} sources: {[x.displayName for x in sources]}")

        smap = {x.id: x.displayName for x in sources}
        results = await s.search_all(smap, "frieren")
        assert any(m.id == 97 for m in results), "manga 97 not in results"
        hit = next(m for m in results if m.id == 97)
        assert hit.inLibrary and hit.source_name
        print(f"{PASS} search_all: '{hit.title}' [{hit.source_name}] inLibrary={hit.inLibrary}")

        chs = await s.chapters_status([385, 386])
        assert all(c.isDownloaded for c in chs), chs
        print(f"{PASS} chapters_status: 385/386 isDownloaded=True")

        st = await s.download_status()
        print(f"{PASS} download_status: state={st.state} queue={len(st.queue)}")
    finally:
        await s.aclose()

    k = KomgaClient(
        os.environ["KOMGA_URL"],
        os.environ["KOMGA_API_KEY"],
        os.environ["KOMGA_LIBRARY_ID"],
    )
    try:
        ok = await k.trigger_scan()
        assert ok, "Komga scan not accepted (expected HTTP 202)"
        print(f"{PASS} komga scan trigger: 202 Accepted")
    finally:
        await k.aclose()

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
