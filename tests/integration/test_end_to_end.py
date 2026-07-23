"""End-to-end test: discover ROMs, scrape with FakeProvider, generate outputs."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import HttpUrl

from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.orchestrator import Orchestrator
from multiscraper.models import (
    Candidate,
    MediaRef,
    MediaType,
    Rom,
    RomIdentifier,
)
from multiscraper.output.db import Database
from multiscraper.providers.registry import ProviderRegistry


class FakeProvider:
    """Provider that returns a candidate with all wanted media types."""

    name = "fake"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 100.0
    priority = 1
    supported_media = {MediaType.IMAGE, MediaType.VIDEO, MediaType.MARQUEE}  # noqa: RUF012
    platform_map: dict[str, str | int] = {"snes": 4}  # noqa: RUF012
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return [
            Candidate(
                provider="fake",
                source_id="1",
                name=rom.normalized_name,
                match_score=0.95,
                description="A great game.",
                media=[
                    MediaRef(
                        type=MediaType.IMAGE,
                        url=HttpUrl("https://example.com/img.jpg"),
                        ext="jpg",
                        source="fake",
                    ),
                    MediaRef(
                        type=MediaType.VIDEO,
                        url=HttpUrl("https://example.com/vid.mp4"),
                        ext="mp4",
                        source="fake",
                    ),
                    MediaRef(
                        type=MediaType.MARQUEE,
                        url=HttpUrl("https://example.com/marquee.png"),
                        ext="png",
                        source="fake",
                    ),
                ],
            )
        ]

    async def fetch_media(
        self,
        candidate: Candidate,
        wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        return {ref.type: ref for mt in wanted for ref in candidate.media if ref.type == mt}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


@pytest.mark.asyncio
async def test_e2e_full_pipeline(tmp_path: Path) -> None:
    """Full pipeline: ROMs → cascade → CSV → DB → gamelist.xml."""
    roms: list[Rom] = []
    for i in range(10):
        ri = RomIdentifier(
            rel_path=f"./snes/game{i}.smc",
            size=1024,
            mtime=1700000000,
            crc32=f"crc{i:08x}",
            cache_key=f"key{i}",
        )
        roms.append(
            Rom(
                system="snes",
                rom_id=ri,
                raw_name=f"game{i}.smc",
                normalized_name=f"Game {i}",
            )
        )

    reg = ProviderRegistry()
    reg.register(FakeProvider())

    config = MultiscraperConfig()
    config.orchestrator = OrchestratorConfig(
        workers=4,
        batch_size=5,
        shutdown_drain_timeout_sec=30,
    )

    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "run.csv"
    media_root = tmp_path / "media"

    orch = Orchestrator(
        registry=reg,
        config=config,
        db_path=str(db_path),
        csv_path=csv_path,
        media_root=media_root,
    )

    run_id = await orch.start(roms=roms, systems=["snes"])
    assert run_id
    await orch.close()

    assert csv_path.exists()
    csv_content = csv_path.read_text()
    lines = csv_content.strip().splitlines()
    assert len(lines) == 11
    assert "OK" in csv_content or "PARTIAL" in csv_content

    db = Database(str(db_path))
    await db.init()
    tables = await db.list_tables()
    assert "runs" in tables
    assert "roms" in tables
    assert "scrape_results" in tables
    await db.close()
