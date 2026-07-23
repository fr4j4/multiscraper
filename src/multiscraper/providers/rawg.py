"""RAWG provider for multiscraper.

Auth: api_key passed as ?key= query param.
Search: GET /api/games?search=<name>.
Media: background_image is used for both IMAGE and THUMBNAIL.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://api.rawg.io/api"

_PLATFORM_MAP: dict[str, str] = {
    "snes": "snes",
    "nes": "nes",
    "n64": "nintendo-64",
    "gb": "game-boy",
    "gba": "game-boy-advance",
    "gbc": "game-boy-color",
    "nds": "nintendo-ds",
    "psx": "playstation",
    "ps2": "playstation-2",
    "ps3": "playstation-3",
    "psp": "psp",
    "megadrive": "genesis",
    "saturn": "sega-saturn",
    "dreamcast": "dreamcast",
    "arcade": "arcade",
    "mame": "arcade",
    "wii": "wii",
    "wiiu": "wii-u",
    "switch": "nintendo-switch",
    "gc": "gamecube",
    "xbox": "xbox",
    "xbox360": "xbox-360",
}


class RAWGProvider:
    """RAWG video game database provider."""

    name: ClassVar[str] = "rawg"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["api_key"]
    rate_limit_per_sec: ClassVar[float] = 5.0
    priority: ClassVar[int] = 30
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
            "key": self._api_key,
            "search": rom.normalized_name,
            "page_size": "10",
        }
        url = f"{_API_BASE}/games"
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

        results = data.get("results", [])
        if not isinstance(results, list):
            return []

        candidates: list[Candidate] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name", "")).strip()
            if not name:
                continue
            sid = str(r.get("id", ""))
            score = compute_match_score(rom.normalized_name, name)
            rating = r.get("rating")
            rating_f: float | None = float(rating) if isinstance(rating, (int, float)) else None
            description = r.get("description") or None
            media_refs = self._build_media(r)
            candidates.append(Candidate(
                provider=self.name,
                source_id=sid,
                name=name,
                match_score=score,
                rating=rating_f,
                description=description,
                genre=self._first_genre(r),
                media=media_refs,
            ))
        return candidates

    def _first_genre(self, game: dict[str, Any]) -> str | None:
        genres = game.get("genres")
        if isinstance(genres, list) and genres:
            first = genres[0]
            if isinstance(first, dict):
                gname = first.get("name")
                if isinstance(gname, str):
                    return gname
        return None

    def _build_media(self, game: dict[str, Any]) -> list[MediaRef]:
        bg = game.get("background_image")
        if not isinstance(bg, str) or not bg:
            return []
        return [
            MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl(bg),
                ext="jpg",
                source=self.name,
            ),
            MediaRef(
                type=MediaType.THUMBNAIL,
                url=HttpUrl(bg),
                ext="jpg",
                source=self.name,
            ),
        ]

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
