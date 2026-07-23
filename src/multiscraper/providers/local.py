"""Local override/fallback provider for multiscraper.

Auth: none required.
Source: SQLite source_overrides table (queried via Database.get_override_by_cache_key).
is_offline: True (no network access).

One class serves both roles:
- local_override: high priority (configured in sources.yaml), provides a curated override.
- local_fallback: lowest priority, fills in when nothing else matches.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.output.db import Database


class LocalProvider:
    """Local override/fallback provider backed by source_overrides table."""

    name: ClassVar[str] = "local"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1000.0
    priority: ClassVar[int] = 1
    supported_media: ClassVar[set[MediaType]] = {
        MediaType.IMAGE, MediaType.THUMBNAIL, MediaType.VIDEO,
        MediaType.MARQUEE, MediaType.BOX3D, MediaType.BACKCOVER,
        MediaType.FANART, MediaType.MANUAL, MediaType.MIXIMAGE, MediaType.LOGO,
    }
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = True
    health_url: ClassVar[str | None] = None

    def __init__(self, db: Database) -> None:
        self._db = db

    async def setup(self, config: dict[str, Any]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        row = await self._db.get_override_by_cache_key(rom.rom_id.cache_key)
        if not row:
            return []
        return [Candidate(
            provider=self.name,
            source_id=row["cache_key"],
            name=row["name"],
            match_score=1.0,
            description=row.get("desc"),
            media=self._build_media_refs(row),
        )]

    def _build_media_refs(self, row: dict[str, Any]) -> list[MediaRef]:
        media_paths = json.loads(row.get("media_paths_json") or "{}")
        result: list[MediaRef] = []
        for mt_str, path in media_paths.items():
            try:
                mt = MediaType(mt_str)
            except ValueError:
                continue
            ext = path.rsplit(".", 1)[-1] if "." in path else "png"
            url = path if "://" in path else f"http://local/{path.lstrip('/')}"
            result.append(MediaRef(
                type=mt,
                url=HttpUrl(url),
                ext=ext,
                source=self.name,
            ))
        return result

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
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False
