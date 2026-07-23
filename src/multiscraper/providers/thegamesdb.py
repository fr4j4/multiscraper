"""TheGamesDB provider for multiscraper (experimental v2).

Auth: api_key passed as ?apikey=<key> query param.
Search: GET /v2/Games/ByGameName?name=<name>.
Media: not populated in v1 (returns Candidates with empty media).
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://api.thegamesdb.net/v2"

_PLATFORM_MAP: dict[str, int] = {
    "snes": 6,
    "nes": 7,
    "n64": 3,
    "gb": 4,
    "gba": 5,
    "gbc": 41,
    "nds": 8,
    "psx": 10,
    "ps2": 11,
    "psp": 13,
    "megadrive": 1,
    "saturn": 17,
    "dreamcast": 18,
}


class TheGamesDBProvider:
    """TheGamesDB v2 API provider."""

    name: ClassVar[str] = "thegamesdb"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["api_key"]
    rate_limit_per_sec: ClassVar[float] = 1.0
    priority: ClassVar[int] = 35
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE, MediaType.THUMBNAIL}
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._api_key: str = ""
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._api_key = str(config.get("api_key", ""))
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None or not self._api_key:
            return []
        params: dict[str, str] = {
            "apikey": self._api_key,
            "name": rom.normalized_name,
        }
        url = f"{_API_BASE}/Games/ByGameName"
        async with self._session.get(url, params=params) as resp:
            body = await resp.read()
            if self.detect_blocked(resp, body):
                return []
            if resp.status != 200:
                return []
            try:
                data: dict[str, Any] = await resp.json(content_type=None)
            except Exception:
                return []

        inner = data.get("data", {})
        if not isinstance(inner, dict):
            return []
        games = inner.get("games", [])
        if not isinstance(games, list):
            return []

        candidates: list[Candidate] = []
        for g in games:
            if not isinstance(g, dict):
                continue
            name = str(g.get("name", "")).strip()
            if not name:
                continue
            gid = g.get("id", "")
            score = compute_match_score(rom.normalized_name, name)
            candidates.append(Candidate(
                provider=self.name,
                source_id=str(gid),
                name=name,
                match_score=score,
            ))
        return candidates

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        result: dict[MediaType, MediaRef] = {}
        for mt in wanted:
            for ref in candidate.media:
                if ref.type == mt and mt not in result:
                    result[mt] = ref
                    break
        return result

    def detect_blocked(self, response: object, body: bytes) -> bool:
        status = getattr(response, "status", 200)
        headers_obj = getattr(response, "headers", {})
        headers: dict[str, str] = {str(k): str(v) for k, v in dict(headers_obj).items()}
        return detect_blocked(status, body, headers)

    def is_auth_missing(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "api_key" in msg or "401" in msg or "403" in msg
