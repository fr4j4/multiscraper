"""Tests for skip-existing logic and per-system CSV output.

These tests verify the Phase 3 features:
- ROMs with existing OK results in DB are skipped (no API call)
- ROMs with changed hash are re-scraped
- --force-rescrape overrides skip
- CSV files are generated per system, not per run
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from multiscraper.config.models import MultiscraperConfig
from multiscraper.models import (
    Candidate,
    MediaRef,
    MediaType,
    Rom,
)
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.scrape import run_scrape_skeleton


class FakeMatchingProvider:
    """Returns one match for any ROM."""

    name: ClassVar[str] = "fake_match"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1000.0
    priority: ClassVar[int] = 1
    supported_media: ClassVar[set[MediaType]] = set()
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = True
    health_url: ClassVar[str | None] = None

    def __init__(self) -> None:
        self.search_count = 0

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        self.search_count += 1
        return [
            Candidate(
                provider=self.name,
                source_id=f"src-{rom.raw_name}",
                name=f"Match for {rom.normalized_name}",
                match_score=0.95,
            )
        ]

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


def _write_yaml_configs(cfg_dir: Path, base_path: Path, systems: list[dict[str, Any]]) -> None:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        yaml.safe_dump({
            "transports": [{"name": "local", "kind": "local", "base_path": str(base_path)}],
            "current_transport": "local",
            "defaults": {},
            "orchestrator": {"workers": 2, "batch_size": 50, "csv_flush_every": 1},
        }), encoding="utf-8",
    )
    (cfg_dir / "sources.yaml").write_text(
        yaml.safe_dump({"providers": [], "provider_defaults": {"match_threshold": 0.7}}),
        encoding="utf-8",
    )
    (cfg_dir / "systems.yaml").write_text(
        yaml.safe_dump({"systems": systems}), encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scrape_skips_existing_ok(tmp_path: Path) -> None:
    """Second run with same hash should skip the ROM (no API call)."""
    from multiscraper.transport.local import LocalTransport

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(b"ROM-CONTENT-1234")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_dir = tmp_path / "reports"
    csv_dir.mkdir()
    media_root = tmp_path / "media"

    _write_yaml_configs(cfg_dir, roms_dir, [
        {"name": "gba", "full_path": str(roms_dir), "extensions": ["gba"]},
    ])

    transport = LocalTransport()
    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    # First run: scrapes the ROM
    summary1 = await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry, sources_config=sources_cfg,
        transport=transport, skip_existing=True, force_rescrape=False,
    )
    assert summary1.roms_matched == 1
    assert provider.search_count == 1

    # Second run: should skip (same hash, OK result in DB)
    transport2 = LocalTransport()
    provider2 = FakeMatchingProvider()
    registry2 = ProviderRegistry()
    registry2.register(provider2)

    summary2 = await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry2, sources_config=sources_cfg,
        transport=transport2, skip_existing=True, force_rescrape=False,
    )
    assert summary2.roms_skipped == 1
    assert summary2.roms_matched == 0
    assert provider2.search_count == 0  # No API call made


@pytest.mark.asyncio
async def test_scrape_rescrapes_when_hash_changed(tmp_path: Path) -> None:
    """If the ROM's hash changed, re-scrape even with skip_existing."""
    from multiscraper.transport.local import LocalTransport

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(b"ROM-V1")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_dir = tmp_path / "reports"
    csv_dir.mkdir()
    media_root = tmp_path / "media"

    _write_yaml_configs(cfg_dir, roms_dir, [
        {"name": "gba", "full_path": str(roms_dir), "extensions": ["gba"]},
    ])

    transport = LocalTransport()
    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry, sources_config=sources_cfg,
        transport=transport, skip_existing=True, force_rescrape=False,
    )
    assert provider.search_count == 1

    # Modify the ROM (hash changes)
    (roms_dir / "game.gba").write_bytes(b"ROM-V2-DIFFERENT-CONTENT")

    transport2 = LocalTransport()
    provider2 = FakeMatchingProvider()
    registry2 = ProviderRegistry()
    registry2.register(provider2)

    summary2 = await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry2, sources_config=sources_cfg,
        transport=transport2, skip_existing=True, force_rescrape=False,
    )
    assert summary2.roms_skipped == 0
    assert summary2.roms_matched == 1
    assert provider2.search_count == 1  # Re-scraped because hash changed


@pytest.mark.asyncio
async def test_scrape_force_rescrape_overrides_skip(tmp_path: Path) -> None:
    """--force-rescrape re-scrapes even when an OK result exists."""
    from multiscraper.transport.local import LocalTransport

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(b"ROM-CONTENT")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_dir = tmp_path / "reports"
    csv_dir.mkdir()
    media_root = tmp_path / "media"

    _write_yaml_configs(cfg_dir, roms_dir, [
        {"name": "gba", "full_path": str(roms_dir), "extensions": ["gba"]},
    ])

    transport = LocalTransport()
    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry, sources_config=sources_cfg,
        transport=transport, skip_existing=True, force_rescrape=False,
    )

    # Force rescrape
    transport2 = LocalTransport()
    provider2 = FakeMatchingProvider()
    registry2 = ProviderRegistry()
    registry2.register(provider2)

    summary2 = await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=["gba"], limit=None,
        registry=registry2, sources_config=sources_cfg,
        transport=transport2, skip_existing=True, force_rescrape=True,
    )
    assert summary2.roms_matched == 1
    assert provider2.search_count == 1


@pytest.mark.asyncio
async def test_scrape_creates_csv_per_system(tmp_path: Path) -> None:
    """Each system gets its own CSV file in the csv_dir."""
    from multiscraper.transport.local import LocalTransport

    roms_dir = tmp_path / "roms"
    gba_dir = roms_dir / "gba"
    snes_dir = roms_dir / "snes"
    gba_dir.mkdir(parents=True)
    snes_dir.mkdir(parents=True)
    (gba_dir / "game1.gba").write_bytes(b"GBA-1")
    (snes_dir / "game1.smc").write_bytes(b"SNES-1")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_dir = tmp_path / "reports"
    media_root = tmp_path / "media"

    _write_yaml_configs(cfg_dir, roms_dir, [
        {"name": "gba", "full_path": str(gba_dir), "extensions": ["gba"]},
        {"name": "snes", "full_path": str(snes_dir), "extensions": ["smc"]},
    ])

    transport = LocalTransport()
    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    await run_scrape_skeleton(
        config_dir=cfg_dir, db_path=db_path, csv_dir=csv_dir,
        media_root=media_root, systems_filter=None, limit=None,
        registry=registry, sources_config=sources_cfg,
        transport=transport, skip_existing=False, force_rescrape=False,
    )

    gba_csv = csv_dir / "scrape_gba.csv"
    snes_csv = csv_dir / "scrape_snes.csv"
    assert gba_csv.exists(), f"missing {gba_csv}"
    assert snes_csv.exists(), f"missing {snes_csv}"
    assert "game1.gba" in gba_csv.read_text(encoding="utf-8")
    assert "game1.smc" in snes_csv.read_text(encoding="utf-8")
