"""End-to-end skeleton tests for the `multiscraper scrape` command.

Verifies that the skeleton CLI scrape function wires up the existing
Orchestrator + LocalTransport + Database + CsvWriter correctly, and that
the public behavior (extension filter, --limit, no-match) works.
"""

from __future__ import annotations

import asyncio
import csv
import sqlite3
import zlib
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from click.testing import CliRunner
from pydantic import HttpUrl

from multiscraper.cli import main
from multiscraper.config.models import MultiscraperConfig, ProviderDefaults
from multiscraper.models import (
    Candidate,
    MediaRef,
    MediaType,
    Rom,
)
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.scrape import SkeletonSummary, _make_rom, run_scrape_skeleton
from multiscraper.transport.local import LocalTransport


class FakeMatchingProvider:
    """A provider that returns one high-quality match for any ROM."""

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
                description=f"Description for {rom.normalized_name}",
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


class FakeNoMatchProvider:
    """A provider that returns no results for any ROM."""

    name: ClassVar[str] = "fake_nomatch"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1000.0
    priority: ClassVar[int] = 1
    supported_media: ClassVar[set[MediaType]] = set()
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = True
    health_url: ClassVar[str | None] = None

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return []

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


class FakeErroringProvider:
    """A provider that raises on search (used to test error tolerance)."""

    name: ClassVar[str] = "fake_error"
    requires_auth: ClassVar[bool] = False
    auth_fields: ClassVar[list[str]] = []
    rate_limit_per_sec: ClassVar[float] = 1000.0
    priority: ClassVar[int] = 1
    supported_media: ClassVar[set[MediaType]] = set()
    platform_map: ClassVar[dict[str, str | int]] = {}
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = True
    health_url: ClassVar[str | None] = None

    async def setup(self, config: dict[str, object]) -> None:
        pass

    async def close(self) -> None:
        pass

    async def search(self, rom: Rom) -> list[Candidate]:
        raise RuntimeError("provider exploded")

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return False

    def is_auth_missing(self, exc: Exception) -> bool:
        return False


def _write_yaml_configs(
    cfg_dir: Path,
    *,
    base_path: Path,
    systems: list[dict[str, Any]],
) -> None:
    """Write the three YAMLs needed for run_scrape_skeleton to a cfg_dir."""
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config_yaml = {
        "transports": [
            {
                "name": "local",
                "kind": "local",
                "base_path": str(base_path),
            }
        ],
        "current_transport": "local",
        "defaults": {},
        "orchestrator": {
            "workers": 2,
            "batch_size": 50,
            "csv_flush_every": 1,
        },
    }
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump(config_yaml), encoding="utf-8")
    sources_yaml = {"providers": [], "provider_defaults": {"match_threshold": 0.7}}
    (cfg_dir / "sources.yaml").write_text(
        yaml.safe_dump(sources_yaml), encoding="utf-8"
    )
    systems_yaml = {"systems": systems}
    (cfg_dir / "systems.yaml").write_text(
        yaml.safe_dump(systems_yaml), encoding="utf-8"
    )


def _make_rom_bytes(content: bytes = b"ROM-CONTENT-1234") -> bytes:
    return content


def _count_db_rows(db_path: Path) -> int:
    """Count rows in the scrape_results table (used to assert '1 DB row')."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM scrape_results")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _count_csv_rows(csv_path: Path) -> int:
    """Count data rows in the CSV file (header excluded)."""
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return 0
    return len(rows) - 1


@pytest.mark.asyncio
async def test_scrape_one_rom_end_to_end(tmp_path: Path) -> None:
    """One ROM, FakeMatchingProvider, 1 DB row, 1 CSV row, correct match."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(_make_rom_bytes())

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

    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()
    sources_cfg.provider_defaults = ProviderDefaults(match_threshold=0.7)

    summary = await run_scrape_skeleton(
        config_dir=cfg_dir,
        db_path=db_path,
        csv_dir=csv_path,
        media_root=media_root,
        systems_filter=["gba"],
        limit=None,
        registry=registry,
        sources_config=sources_cfg,
    )

    assert isinstance(summary, SkeletonSummary)
    assert summary.roms_total == 1
    assert summary.roms_matched == 1
    assert summary.roms_no_match == 0
    assert summary.errors == 0
    assert len(provider.searches) == 1
    assert provider.searches[0].raw_name == "game.gba"
    assert _count_db_rows(db_path) == 1
    assert _count_csv_rows(csv_path / "scrape_gba.csv") == 1
    csv_lines = (csv_path / "scrape_gba.csv").read_text(encoding="utf-8").splitlines()
    assert "OK" in csv_lines[1] or "PARTIAL" in csv_lines[1]


@pytest.mark.asyncio
async def test_scrape_filters_by_extension(tmp_path: Path) -> None:
    """Only .gba files are processed; .txt is skipped."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "real.gba").write_bytes(_make_rom_bytes(b"real-rom"))
    (roms_dir / "notes.txt").write_text("this is not a rom")
    (roms_dir / "readme.md").write_text("# readme")

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

    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    summary = await run_scrape_skeleton(
        config_dir=cfg_dir,
        db_path=db_path,
        csv_dir=csv_path,
        media_root=media_root,
        systems_filter=None,
        limit=None,
        registry=registry,
        sources_config=sources_cfg,
    )

    assert summary.roms_total == 1
    assert len(provider.searches) == 1
    assert provider.searches[0].raw_name == "real.gba"


@pytest.mark.asyncio
async def test_scrape_respects_limit(tmp_path: Path) -> None:
    """5 ROMs, --limit 2, only 2 processed."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    for i in range(5):
        (roms_dir / f"game{i}.gba").write_bytes(_make_rom_bytes(f"rom-{i}".encode()))

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

    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    summary = await run_scrape_skeleton(
        config_dir=cfg_dir,
        db_path=db_path,
        csv_dir=csv_path,
        media_root=media_root,
        systems_filter=None,
        limit=2,
        registry=registry,
        sources_config=sources_cfg,
    )

    assert summary.roms_total == 2
    assert len(provider.searches) == 2
    assert _count_db_rows(db_path) == 2
    assert _count_csv_rows(csv_path / "scrape_gba.csv") == 2


@pytest.mark.asyncio
async def test_scrape_handles_no_match(tmp_path: Path) -> None:
    """Provider returns nothing: no DB row, no CSV row, no error."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "game.gba").write_bytes(_make_rom_bytes())

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

    provider = FakeNoMatchProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    summary = await run_scrape_skeleton(
        config_dir=cfg_dir,
        db_path=db_path,
        csv_dir=csv_path,
        media_root=media_root,
        systems_filter=None,
        limit=None,
        registry=registry,
        sources_config=sources_cfg,
    )

    assert summary.roms_total == 1
    assert summary.roms_no_match == 1
    assert summary.roms_matched == 0
    assert summary.errors == 0
    assert _count_db_rows(db_path) == 1
    assert _count_csv_rows(csv_path / "scrape_gba.csv") == 1


@pytest.mark.asyncio
async def test_scrape_handles_transport_error(tmp_path: Path) -> None:
    """A system path that doesn't exist returns 0 ROMs, no crash."""
    roms_dir = tmp_path / "roms_does_not_exist"

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

    provider = FakeMatchingProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    sources_cfg = MultiscraperConfig()

    summary = await run_scrape_skeleton(
        config_dir=cfg_dir,
        db_path=db_path,
        csv_dir=csv_path,
        media_root=media_root,
        systems_filter=None,
        limit=None,
        registry=registry,
        sources_config=sources_cfg,
    )

    assert summary.roms_total == 0
    assert summary.roms_matched == 0
    assert summary.roms_no_match == 0
    assert summary.errors == 0
    assert len(provider.searches) == 0


def test_scrape_computes_hash(tmp_path: Path) -> None:
    """_make_rom must populate rom.rom_id.crc32 from the file contents."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    content = b"ROM-CONTENT-1234"
    (roms_dir / "game.gba").write_bytes(content)

    transport = LocalTransport()
    rom = asyncio.run(
        _make_rom(
            transport=transport,
            system="gba",
            system_path=str(roms_dir),
            filename="game.gba",
            hash_algo="crc32",
        )
    )
    asyncio.run(transport.close())

    expected = f"{zlib.crc32(content) & 0xFFFFFFFF:08x}"
    assert rom.rom_id.crc32 == expected
    assert rom.rom_id.cache_key.endswith(expected)


def test_cli_scrape_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`multiscraper scrape --dry-run` prints settings and exits 0."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scrape",
            "--dry-run",
            "--config", "nonexistent.yaml",
            "--roms-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
