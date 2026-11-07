import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class SonarrError(Exception):
    pass


class SonarrClient:
    """Minimal async client for the parts of the Sonarr v3 API the bot needs."""

    def __init__(self, url: str, api_key: str, timeout: int = 30):
        self._base = url.rstrip("/") + "/api/v3"
        self._headers = {"X-Api-Key": api_key}
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with aiohttp.ClientSession(timeout=self._timeout, headers=self._headers) as session:
                async with session.request(method, self._base + path, **kwargs) as response:
                    if response.status >= 400:
                        raise SonarrError(f"Sonarr answered {response.status}: {(await response.text())[:200]}")
                    return await response.json()
        except aiohttp.ClientError as e:
            raise SonarrError(f"could not reach Sonarr ({type(e).__name__})") from e

    async def lookup(self, term: str) -> list:
        return await self._request("GET", "/series/lookup", params={"term": term})

    async def lookup_tvdb(self, tvdb_id: int) -> Optional[dict]:
        found = await self.lookup(f"tvdb:{tvdb_id}")
        return found[0] if found else None

    async def existing_tvdb_ids(self) -> set:
        return {s.get("tvdbId") for s in await self._request("GET", "/series")}

    async def quality_profiles(self) -> list:
        return await self._request("GET", "/qualityprofile")

    async def add_series(self, payload: dict) -> dict:
        return await self._request("POST", "/series", json=payload)
