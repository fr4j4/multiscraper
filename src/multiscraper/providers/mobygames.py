"""MobyGames provider for multiscraper.

Auth: api_key passed as ?api_key= query param.
Search: GET /v1/games?title=<name>.
Media: per-game GET /v1/games/{id}/covers, first cover used for IMAGE.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://api.mobygames.com/v1"

_PLATFORM_MAP: dict[str, int] = {
    "snes": 15, "nes": 23, "n64": 10, "gb": 12, "gba": 17, "gbc": 11, "nds": 8,
    "psx": 6, "ps2": 7, "psp": 18, "ps3": 11,
    "megadrive": 16, "saturn": 17, "dreamcast": 20,
}


class MobyGamesProvider:
    """MobyGames API v1 provider."""

    name: ClassVar[str] = "mobygames"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["api_key"]
    rate_limit_per_sec: ClassVar[float] = 1.0
    priority: ClassVar[int] = 15
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE, MediaType.THUMBNAIL}
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False
    health_url: ClassVar[str | None] = "https://api.mobygames.com/v1/"

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
            "api_key": self._api_key,
            "title": rom.normalized_name,
            "limit": "10",
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

        games = data.get("games", [])
        if not isinstance(games, list):
            return []

        candidates: list[Candidate] = []
        for g in games:
            if not isinstance(g, dict):
                continue
            name = str(g.get("title", "")).strip()
            if not name:
                continue
            gid = g.get("game_id", "")
            score = compute_match_score(rom.normalized_name, name)
            description = g.get("description") or None
            genre = self._first_genre(g)
            media_refs = await self._fetch_cover(int(gid)) if isinstance(gid, int) else []
            candidates.append(Candidate(
                provider=self.name,
                source_id=str(gid),
                name=name,
                match_score=score,
                description=description,
                genre=genre,
                media=media_refs,
            ))
        return candidates

    def _first_genre(self, game: dict[str, Any]) -> str | None:
        genres = game.get("genres")
        if isinstance(genres, list) and genres:
            first = genres[0]
            if isinstance(first, dict):
                gname = first.get("genre_name")
                if isinstance(gname, str):
                    return gname
        return None

    async def _fetch_cover(self, game_id: int) -> list[MediaRef]:
        if self._session is None or not self._api_key:
            return []
        params: dict[str, str] = {"api_key": self._api_key}
        url = f"{_API_BASE}/games/{game_id}/covers"
        try:
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
        except Exception:
            return []
        covers = data.get("covers", [])
        if not isinstance(covers, list) or not covers:
            return []
        first = covers[0]
        if not isinstance(first, dict):
            return []
        image = first.get("image")
        if not isinstance(image, str) or not image:
            return []
        return [
            MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl(image),
                ext="jpg",
                source=self.name,
            ),
            MediaRef(
                type=MediaType.THUMBNAIL,
                url=HttpUrl(image),
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
