"""LibRetro Thumbnails provider for multiscraper.

Auth: none required.
Search: probes multiple libretro-thumbnails GitHub raw URL patterns via HEAD
and returns a single Candidate per ROM if at least one probe succeeds.
Media: Named_Snaps -> IMAGE, Named_Boxarts -> BOX3D, Named_Titles -> LOGO,
Standard_Boxarts -> IMAGE.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked

_RAW_BASE = "https://raw.githubusercontent.com/libretro-thumbnails"
_PATTERNS: list[tuple[str, MediaType, str]] = [
    ("Named_Snaps", MediaType.IMAGE, "png"),
    ("Named_Boxarts", MediaType.BOX3D, "png"),
    ("Named_Titles", MediaType.LOGO, "png"),
    ("Standard_Boxarts", MediaType.IMAGE, "png"),
]


class LibRetroThumbnailsProvider:
    """LibRetro Thumbnails probe-based provider."""

    name: ClassVar[str] = "libretro_thumbnails"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 0.5
    priority: ClassVar[int] = 40
    supported_media: ClassVar[set[MediaType]] = {
        MediaType.IMAGE, MediaType.BOX3D, MediaType.LOGO,
    }
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None:
            return []
        rom_name = self._normalize_name(rom.normalized_name)
        if not rom_name:
            return []
        media_refs: list[MediaRef] = []
        for folder, media_type, ext in _PATTERNS:
            url = f"{_RAW_BASE}/{rom.system}/master/{folder}/{rom_name}.{ext}"
            try:
                async with self._session.head(url) as resp:
                    if resp.status == 200:
                        media_refs.append(MediaRef(
                            type=media_type,
                            url=HttpUrl(url),
                            ext=ext,
                            source=self.name,
                        ))
            except Exception:
                continue
        if not media_refs:
            return []
        return [Candidate(
            provider=self.name,
            source_id=rom_name,
            name=rom.normalized_name,
            match_score=1.0,
            media=media_refs,
        )]

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.replace(" ", "_")

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
