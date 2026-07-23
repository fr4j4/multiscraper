"""RetroAchievements provider for multiscraper.

Auth: username + api_key passed as ?z=<user>&y=<key> query params.
Search: GET /API/API_GetGameList.php with a global list (i=10, f=1).
Media: ImageIcon -> IMAGE, ImageTitle -> LOGO.
"""

from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_API_BASE = "https://retroachievements.org/API"

_PLATFORM_MAP: dict[str, int] = {
    "nes": 7,
    "snes": 3,
    "n64": 2,
    "gb": 4,
    "gba": 5,
    "gbc": 6,
    "nds": 14,
    "psx": 12,
    "ps2": 21,
    "psp": 13,
    "megadrive": 1,
    "saturn": 17,
    "dreamcast": 18,
    "gamegear": 15,
    "atari2600": 23,
    "lynx": 13,
    "arcade": 27,
    "mame": 27,
}


class RetroAchievementsProvider:
    """RetroAchievements API provider."""

    name: ClassVar[str] = "retroachievements"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["username", "api_key"]
    rate_limit_per_sec: ClassVar[float] = 1.0
    priority: ClassVar[int] = 25
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE, MediaType.LOGO}
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._username: str = ""
        self._api_key: str = ""
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._username = str(config.get("username", ""))
        self._api_key = str(config.get("api_key", ""))
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None or not self._api_key or not self._username:
            return []
        params: dict[str, str] = {
            "z": self._username,
            "y": self._api_key,
            "i": "10",
            "f": "1",
        }
        url = f"{_API_BASE}/API_GetGameList.php"
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

        results = data.get("Response", [])
        if not isinstance(results, list):
            return []

        target = rom.normalized_name.lower()
        candidates: list[Candidate] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            name = str(r.get("Title", "")).strip()
            if not name:
                continue
            score = compute_match_score(rom.normalized_name, name)
            if score < 0.5 and target not in name.lower():
                continue
            sid = str(r.get("ID", ""))
            media_refs = self._build_media(r)
            candidates.append(Candidate(
                provider=self.name,
                source_id=sid,
                name=name,
                match_score=score,
                media=media_refs,
            ))
        return candidates

    def _build_media(self, game: dict[str, Any]) -> list[MediaRef]:
        media: list[MediaRef] = []
        icon = game.get("ImageIcon")
        if isinstance(icon, str) and icon:
            url = icon if icon.startswith("http") else f"https://retroachievements.org{icon}"
            media.append(MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl(url),
                ext="png",
                source=self.name,
            ))
        title = game.get("ImageTitle")
        if isinstance(title, str) and title:
            url = title if title.startswith("http") else f"https://retroachievements.org{title}"
            media.append(MediaRef(
                type=MediaType.LOGO,
                url=HttpUrl(url),
                ext="png",
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
