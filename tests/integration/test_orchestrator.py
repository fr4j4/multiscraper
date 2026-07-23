"""Integration test for the orchestrator with FakeProvider and FakeTransport."""

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
from multiscraper.providers.registry import ProviderRegistry


class FakeProvider:
    """Simple provider that always returns a match."""

    name = "fake"
    requires_auth = False
    auth_fields: list[str] = []  # noqa: RUF012
    rate_limit_per_sec = 100.0
    priority = 1
    supported_media = {MediaType.IMAGE}  # noqa: RUF012
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
                description="Fake game.",
            )
        ]

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]:
        return {
            MediaType.IMAGE: MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl("https://example.com/img.jpg"),
                ext="jpg",
                source="fake",
            )
        }

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


@pytest.mark.asyncio
async def test_orchestrator_processes_roms(tmp_path: Path) -> None:
    """Orchestrator should process ROMs and produce output."""
    roms: list[Rom] = []
    for i in range(5):
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
        workers=2, batch_size=10, shutdown_drain_timeout_sec=10,
    )

    orch = Orchestrator(
        registry=reg,
        config=config,
        db_path=str(tmp_path / "test.db"),
        csv_path=tmp_path / "run.csv",
        media_root=tmp_path / "media",
    )

    run_id = await orch.start(roms=roms, systems=["snes"])

    assert (tmp_path / "run.csv").exists()
    db_exists = (tmp_path / "test.db").exists()
    assert db_exists
    assert run_id

    await orch.close()
