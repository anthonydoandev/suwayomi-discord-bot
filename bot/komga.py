"""Minimal Komga REST client — scan trigger only.
Rationale: library scanInterval is 6h with scanOnStartup off; without an
explicit scan a fresh download can sit invisible for hours."""
import httpx


class KomgaClient:
    def __init__(self, base_url: str, api_key: str, library_id: str):
        self._http = httpx.AsyncClient(
            base_url=base_url, headers={"X-API-Key": api_key}, timeout=30.0
        )
        self._library_id = library_id

    async def aclose(self) -> None:
        await self._http.aclose()

    async def trigger_scan(self) -> bool:
        resp = await self._http.post(f"/api/v1/libraries/{self._library_id}/scan")
        return resp.status_code == 202
