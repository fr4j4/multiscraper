"""IGDB provider (Twitch OAuth2) for multiscraper.

Auth via Twitch OAuth2 (client_id + client_secret).
Search POST to /v4/games.
Media URLs built from cover.image_id and screenshots[].image_id.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked
from multiscraper.providers.match import compute_match_score

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_GAMES_URL = "https://api.igdb.com/v4/games"
_IMG_BASE = "https://images.igdb.com/igdb/image/upload"

_PLATFORM_MAP: dict[str, int] = {
    "snes": 19, "nes": 18, "n64": 4, "gb": 33, "gba": 24, "gbc": 22, "nds": 20,
    "psx": 7, "ps2": 8, "psp": 38, "ps3": 9,
    "megadrive": 29, "saturn": 32, "dreamcast": 23, "gamegear": 43,
    "arcade": 52, "mame": 52, "atari2600": 59,
    "wii": 5, "wiiu": 41, "switch": 130, "gc": 21,
    "xbox": 11, "xbox360": 12,
}


class IGDBProvider:
    """IGDB API v4 provider with Twitch OAuth2."""

    name: ClassVar[str] = "igdb"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["client_id", "client_secret"]
    rate_limit_per_sec: ClassVar[float] = 4.0
    priority: ClassVar[int] = 10
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE, MediaType.THUMBNAIL}
    platform_map: ClassVar[dict[str, str | int]] = _PLATFORM_MAP  # type: ignore[assignment]
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._client_id: str = ""
        self._client_secret: str = ""
        self._session: aiohttp.ClientSession | None = None
        self._token: str = ""
        self._token_expiry: float = 0.0

    async def setup(self, config: dict[str, Any]) -> None:
        self._client_id = str(config.get("client_id", ""))
        self._client_secret = str(config.get("client_secret", ""))
        self._session = aiohttp.ClientSession()
        self._token = ""
        self._token_expiry = 0.0

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        if self._session is None:
            raise RuntimeError("IGDBProvider not initialized: session is None")
        params = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }
        async with self._session.post(_TOKEN_URL, params=params) as resp:
            body = await resp.read()
            if resp.status != 200:
                raise RuntimeError(f"IGDB auth failed: status={resp.status} body={body!r}")
            data: dict[str, Any] = await resp.json(content_type=None)
        self._token = str(data.get("access_token", ""))
        expires_in = float(data.get("expires_in", 3600))
        self._token_expiry = time.time() + expires_in - 60.0
        return self._token

    async def search(self, rom: Rom) -> list[Candidate]:
        if self._session is None:
            return []
        if not self._client_id or not self._client_secret:
            return []

        try:
            token = await self._get_token()
        except Exception:
            return []

        platform_id = self.platform_map.get(rom.system)
        where_clause = f"platforms = ({platform_id});" if platform_id is not None else ""
        body_str = (
            f"fields name,summary,rating,genres.name,platforms.name,"
            f"cover.image_id,screenshots.image_id; "
            f'search "{rom.normalized_name}"; {where_clause} limit 10;'
        )
        headers = {
            "Client-ID": self._client_id,
            "Authorization": f"Bearer {token}",
        }
        async with self._session.post(_GAMES_URL, data=body_str, headers=headers) as resp:
            resp_body = await resp.read()
            if self.detect_blocked(resp, resp_body):
                return []
            if resp.status != 200:
                return []
            try:
                games: list[dict[str, Any]] = await resp.json(content_type=None)
            except Exception:
                return []

        candidates: list[Candidate] = []
        for g in games:
            name = str(g.get("name", "")).strip()
            if not name:
                continue
            gid = str(g.get("id", ""))
            score = compute_match_score(rom.normalized_name, name)
            media_refs = self._build_media(g)
            rating_raw = g.get("rating")
            rating: float | None = None
            if isinstance(rating_raw, (int, float)):
                rating = float(rating_raw) / 10.0
            candidates.append(Candidate(
                provider=self.name,
                source_id=gid,
                name=name,
                match_score=score,
                rating=rating,
                description=g.get("summary") or None,
                media=media_refs,
            ))
        return candidates

    def _build_media(self, game: dict[str, Any]) -> list[MediaRef]:
        media: list[MediaRef] = []
        cover = game.get("cover")
        if isinstance(cover, dict):
            image_id = cover.get("image_id")
            if isinstance(image_id, str) and image_id:
                media.append(MediaRef(
                    type=MediaType.IMAGE,
                    url=HttpUrl(f"{_IMG_BASE}/t_cover_big/{image_id}.jpg"),
                    ext="jpg",
                    source=self.name,
                ))
                media.append(MediaRef(
                    type=MediaType.THUMBNAIL,
                    url=HttpUrl(f"{_IMG_BASE}/t_thumb/{image_id}.jpg"),
                    ext="jpg",
                    source=self.name,
                ))
        screenshots = game.get("screenshots")
        if isinstance(screenshots, list):
            for s in screenshots[:1]:
                if isinstance(s, dict):
                    image_id = s.get("image_id")
                    if isinstance(image_id, str) and image_id:
                        media.append(MediaRef(
                            type=MediaType.THUMBNAIL,
                            url=HttpUrl(f"{_IMG_BASE}/t_screenshot_med/{image_id}.jpg"),
                            ext="jpg",
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
        return "client_id" in msg or "client_secret" in msg or "401" in msg or "403" in msg
