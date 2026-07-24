"""Phase 2 tests: cascade multi-provider, media download, Orchestrator.

These tests exercise the real Orchestrator path and verify:
- The CLI does not override YAML's timeout_sec / rate_limit_per_sec
- Media files are saved to media_root/<system>/...
- The skeleton wires discovery + orchestrator.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from pydantic import HttpUrl

from multiscraper.cli import build_sources_config
from multiscraper.config.models import MultiscraperConfig
from multiscraper.core.discovery import discover_system
from multiscraper.models import (
    Candidate,
    MediaRef,
    MediaType,
    Rom,
)
from multiscraper.output.db import Database
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.scrape import SkeletonSummary, run_scrape_skeleton
from multiscraper.transport.local import LocalTransport


class FakeMediaProvider:
    """A provider that returns one match and a single media URL."""

    name: ClassVar[str] = "fake_media"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1000.0
    priority: ClassVar[int] = 1
    supported_media: ClassVar[set[MediaType]] = {MediaType.IMAGE}
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = True
    health_url: ClassVar[str | None] = None

    def __init__(self) -> None:
        self.searches: list[Rom] = []

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        self.searches.append(rom)
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
        return {
            MediaType.IMAGE: MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl("https://example.com/img.png"),
                ext="png",
                source=self.name,
            )
        }

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


def _write_yaml_configs(
    cfg_dir: Path,
    *,
    base_path: Path,
    systems: list[dict[str, Any]],
    sources_provider_defaults: dict[str, Any] | None = None,
) -> None:
    """Write the three YAMLs needed for run_scrape_skeleton to a cfg_dir."""
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config_yaml = {
        "transports": [
            {"name": "local", "kind": "local", "base_path": str(base_path)}
        ],
        "current_transport": "local",
        "defaults": {},
        "orchestrator": {
            "workers": 1,
            "batch_size": 50,
            "csv_flush_every": 1,
        },
    }
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump(config_yaml), encoding="utf-8")

    sources_yaml: dict[str, Any] = {"providers": []}
    sources_yaml["provider_defaults"] = sources_provider_defaults or {
        "match_threshold": 0.7,
    }
    (cfg_dir / "sources.yaml").write_text(
        yaml.safe_dump(sources_yaml), encoding="utf-8"
    )
    (cfg_dir / "systems.yaml").write_text(
        yaml.safe_dump({"systems": systems}), encoding="utf-8"
    )


def _expected_crc32(data: bytes) -> str:
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


@pytest.mark.asyncio
async def test_discovery_populates_db(tmp_path: Path) -> None:
    """discover_system must populate discovered_roms and compute hashes."""
    from multiscraper.config.models import System

    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    content = b"ROM-CONTENT-1234"
    (roms_dir / "game.gba").write_bytes(content)

    db = Database(str(tmp_path / "cache.db"))
    await db.init()
    run_id = await db.create_run(config_json={})

    system = System(name="gba", full_path=str(roms_dir), extensions=["gba"])
    transport = LocalTransport()
    stats = await discover_system(
        db=db,
        transport=transport,
        run_id=run_id,
        system=system,
        system_path=str(roms_dir),
        hash_algo="crc32",
        concurrency=2,
    )
    await transport.close()

    assert stats.listed == 1
    assert stats.hashed == 1
    assert stats.hash_failed == 0
    ready = await db.count_discovered(run_id, system="gba", hash_status="done")
    assert ready == 1

    row = await db.claim_one_discovered(run_id, "gba")
    assert row is not None
    assert row["crc32"] == _expected_crc32(content)
    await db.close()


@pytest.mark.asyncio
async def test_scrape_uses_orchestrator(tmp_path: Path) -> None:
    """run_scrape_skeleton must populate discovered_roms and call Orchestrator.start."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(b"ROM-CONTENT-1234")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_path = tmp_path / "out.csv"
    media_root = tmp_path / "media"

    _write_yaml_configs(
        cfg_dir,
        base_path=roms_dir,
        systems=[{
            "name": "gba", "full_path": str(roms_dir), "extensions": ["gba"],
        }],
    )

    registry = ProviderRegistry()
    registry.register(FakeMediaProvider())
    sources_cfg = MultiscraperConfig()

    with patch("multiscraper.scrape.Orchestrator") as MockOrchestrator:
        mock_instance = MockOrchestrator.return_value
        mock_instance.start = AsyncMock(return_value=None)
        mock_instance.close = AsyncMock(return_value=None)

        await run_scrape_skeleton(
            config_dir=cfg_dir,
            db_path=db_path,
            csv_dir=csv_path,
            media_root=media_root,
            systems_filter=["gba"],
            limit=None,
            registry=registry,
            sources_config=sources_cfg,
        )

    mock_instance.start.assert_awaited_once()
    args, _ = mock_instance.start.call_args
    systems_arg = args[0]
    assert systems_arg == ["gba"]


@pytest.mark.asyncio
async def test_scrape_downloads_media(tmp_path: Path) -> None:
    """run_scrape_skeleton must download media to media_root/<system>/."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(b"ROM-CONTENT-1234")

    cfg_dir = tmp_path / "config"
    db_path = tmp_path / "cache.db"
    csv_path = tmp_path / "out.csv"
    media_root = tmp_path / "media"

    _write_yaml_configs(
        cfg_dir,
        base_path=roms_dir,
        systems=[{
            "name": "gba", "full_path": str(roms_dir), "extensions": ["gba"],
        }],
    )

    registry = ProviderRegistry()
    registry.register(FakeMediaProvider())
    sources_cfg = MultiscraperConfig()

    fake_image = b"FAKE-IMAGE-BYTES"

    async def fake_safe_download(
        url: str, dest: Path, session: object,
    ) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(fake_image)
        return True

    with patch(
        "multiscraper.core.orchestrator.safe_download",
        side_effect=fake_safe_download,
    ):
        await run_scrape_skeleton(
            config_dir=cfg_dir,
            db_path=db_path,
            csv_dir=csv_path,
            media_root=media_root,
            systems_filter=["gba"],
            limit=None,
            registry=registry,
            sources_config=sources_cfg,
        )

    media_files = list((media_root / "gba").iterdir())
    assert media_files, "expected at least one downloaded media file"
    downloaded = media_files[0].read_bytes()
    assert downloaded == fake_image


def test_scrape_uses_yaml_defaults(tmp_path: Path) -> None:
    """The CLI must not override YAML's timeout_sec / rate_limit_per_sec.

    The CLI keeps overriding match_threshold (its flag is named for that),
    but the rest of provider_defaults must come from YAML untouched.
    """
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()

    cfg_dir = tmp_path / "config"
    _write_yaml_configs(
        cfg_dir,
        base_path=roms_dir,
        systems=[{
            "name": "gba", "full_path": str(roms_dir), "extensions": ["gba"],
        }],
        sources_provider_defaults={
            "match_threshold": 0.6,
            "timeout_sec": 12.5,
            "rate_limit_per_sec": 4.25,
        },
    )

    sources_cfg = build_sources_config(cfg_dir / "sources.yaml", match_threshold=0.9)
    assert sources_cfg.provider_defaults.match_threshold == 0.9
    assert sources_cfg.provider_defaults.timeout_sec == 12.5
    assert sources_cfg.provider_defaults.rate_limit_per_sec == 4.25
