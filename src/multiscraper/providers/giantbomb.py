"""GiantBomb provider for multiscraper.

Auth: api_key passed as ?api_key= query param.
Search: GET /api/games/?filter=name:<name>&format=json.
Media: image.screen_url, image.thumb_url, video.site_detail_url.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://www.giantbomb.com/api"

_PLATFORM_MAP: dict[str, str] = {
    "snes": "snes",
    "nes": "nes",
    "n64": "n64",
    "gb": "gb",
    "gba": "gba",
    "gbc": "gbc",
    "nds": "nds",
    "psx": "ps1",
    "ps2": "ps2",
    "ps3": "ps3",
    "psp": "psp",
    "megadrive": "genesis",
    "saturn": "saturn",
    "dreamcast": "dreamcast",
    "wii": "wii",
    "switch": "switch",
    "gc": "gamecube",
    "xbox": "xbox",
    "xbox360": "xbox360",
}


class GiantBombProvider:
    """GiantBomb API provider."""

    name: ClassVar[str] = "giantbomb"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["api_key"]
    rate_limit_per_sec: ClassVar[float] = 0.05
    priority: ClassVar[int] = 20
    supported_media: ClassVar[set[MediaType]] = {
        MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO,
    }
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False
    health_url: ClassVar[str | None] = "https://www.giantbomb.com/api/"

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
            "filter": f"name:{rom.normalized_name}",
            "format": "json",
            "limit": "10",
        }
        url = f"{_API_BASE}/games/"
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
            description = r.get("description") or r.get("deck") or None
            media_refs = self._build_media(r)
            candidates.append(Candidate(
                provider=self.name,
                source_id=sid,
                name=name,
                match_score=score,
                description=description,
                media=media_refs,
            ))
        return candidates

    def _build_media(self, game: dict[str, Any]) -> list[MediaRef]:
        media: list[MediaRef] = []
        image = game.get("image")
        if isinstance(image, dict):
            screen = image.get("screen_url")
            if isinstance(screen, str) and screen:
                media.append(MediaRef(
                    type=MediaType.IMAGE,
                    url=HttpUrl(screen),
                    ext="jpg",
                    source=self.name,
                ))
            thumb = image.get("thumb_url")
            if isinstance(thumb, str) and thumb:
                media.append(MediaRef(
                    type=MediaType.THUMBNAIL,
                    url=HttpUrl(thumb),
                    ext="jpg",
                    source=self.name,
                ))
        video = game.get("video")
        if isinstance(video, dict):
            vurl = video.get("site_detail_url")
            if isinstance(vurl, str) and vurl:
                media.append(MediaRef(
                    type=MediaType.VIDEO,
                    url=HttpUrl(vurl),
                    ext="mp4",
                    source=self.name,
                ))
        return media

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
