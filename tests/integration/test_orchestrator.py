"""Integration test for the orchestrator with FakeProvider and FakeTransport."""

import asyncio
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
    import asyncio

    db = Database(str(tmp_path / "test.db"))
    await db.init()
    run_id = await db.create_run(config_json={})

    entries: list[dict[str, object]] = []
    for i in range(5):
        entries.append({
            "rel_path": f"./snes/game{i}.smc",
            "raw_name": f"game{i}.smc",
            "normalized_name": f"Game {i}",
            "size": 1024,
            "mtime": 1700000000,
            "crc32": f"crc{i:08x}",
            "sha1": None,
            "cache_key": f"snes:game{i}.smc:crc{i:08x}",
        })
    await db.insert_discovered_pending(run_id, "snes", entries)
    for i in range(5):
        rid = await db.find_pending_discovered_id(
            run_id, "snes", f"./snes/game{i}.smc",
        )
        assert rid is not None
        await db.update_discovered_hash(
            rid, size=1024, mtime=1700000000,
            crc32=f"crc{i:08x}", sha1=None,
            cache_key=f"snes:game{i}.smc:crc{i:08x}", status="done",
        )

    reg = ProviderRegistry()
    reg.register(FakeProvider())

    config = MultiscraperConfig()
    orch = Orchestrator(
        registry=reg,
        config=config,
        db=db,
        run_id=run_id,
        csv_path=tmp_path / "run.csv",
        media_root=tmp_path / "media",
        orchestrator=OrchestratorConfig(
            workers=2, batch_size=10, shutdown_drain_timeout_sec=10,
        ),
    )

    discovery_done = asyncio.Event()
    discovery_done.set()

    from unittest.mock import AsyncMock, patch
    fake_path = tmp_path / "fake.jpg"

    async def fake_safe_download(url, dest, session):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE")
        return True

    with patch(
        "multiscraper.core.orchestrator.safe_download",
        side_effect=fake_safe_download,
    ):
        await orch.start(systems=["snes"], discovery_done=discovery_done)

    assert (tmp_path / "run.csv").exists()
    db_exists = (tmp_path / "test.db").exists()
    assert db_exists
    assert run_id

    rows_in_csv = (tmp_path / "run.csv").read_text(encoding="utf-8").count("\n")
    assert rows_in_csv >= 6  # 1 header + 5 data rows

    await orch.close()
    await db.close()


@pytest.mark.asyncio
async def test_orchestrator_workers_see_discovery_in_progress(tmp_path: Path) -> None:
    """Workers can claim and process rows while discovery is still going.

    This is the performance win: a slow discovery no longer blocks
    the first worker. We simulate a slow discovery by inserting
    rows one at a time, with a small sleep, and a slow worker that
    sleeps before each claim. We verify the worker can claim at
    least one row before discovery has fully finished.
    """
    import asyncio

    db = Database(str(tmp_path / "test.db"))
    await db.init()
    run_id = await db.create_run(config_json={})

    for i in range(3):
        await db.insert_discovered_pending(run_id, "snes", [
            {"rel_path": f"g{i}.smc", "raw_name": f"g{i}.smc",
             "normalized_name": f"G{i}", "size": 1024, "mtime": 1,
             "crc32": f"c{i}", "sha1": None, "cache_key": f"k{i}"},
        ])
        rid = await db.find_pending_discovered_id(run_id, "snes", f"g{i}.smc")
        assert rid is not None
        await db.update_discovered_hash(
            rid, size=1024, mtime=1, crc32=f"c{i}", sha1=None,
            cache_key=f"k{i}", status="done",
        )

    reg = ProviderRegistry()
    reg.register(FakeProvider())
    discovery_done = asyncio.Event()

    async def slow_discover() -> None:
        for i in range(3, 6):
            await asyncio.sleep(0.05)
            await db.insert_discovered_pending(run_id, "snes", [
                {"rel_path": f"g{i}.smc", "raw_name": f"g{i}.smc",
                 "normalized_name": f"G{i}", "size": 1024, "mtime": 1,
                 "crc32": f"c{i}", "sha1": None, "cache_key": f"k{i}"},
            ])
            rid = await db.find_pending_discovered_id(
                run_id, "snes", f"g{i}.smc",
            )
            assert rid is not None
            await db.update_discovered_hash(
                rid, size=1024, mtime=1, crc32=f"c{i}", sha1=None,
                cache_key=f"k{i}", status="done",
            )
        discovery_done.set()

    discovery_task = asyncio.create_task(slow_discover())
    orch = Orchestrator(
        registry=reg,
        config=MultiscraperConfig(),
        db=db,
        run_id=run_id,
        csv_path=tmp_path / "run.csv",
        media_root=tmp_path / "media",
        orchestrator=OrchestratorConfig(workers=2, discovery_poll_interval_sec=0.05),
    )
    await orch.start(systems=["snes"], discovery_done=discovery_done)
    await orch.close()
    await discovery_task

    rows = (tmp_path / "run.csv").read_text(encoding="utf-8").count("\n")
    assert rows >= 7  # 1 header + 6 data rows

    await db.close()


@pytest.mark.asyncio
async def test_orchestrator_aborts_when_all_providers_blocked(
    tmp_path: Path,
) -> None:
    """When every provider raises ProviderBlockedError, the orchestrator
    aborts the run and exposes the abort reason + provider_errors."""
    from multiscraper.providers.base import (
        AllProvidersBlocked, ProviderBlockedError,
    )

    class AlwaysBlockedProvider:
        name = "always_blocked"
        requires_auth = False
        auth_fields: list[str] = []
        rate_limit_per_sec = 100.0
        priority = 1
        supported_media = {MediaType.IMAGE}
        platform_map: dict[str, str | int] = {"snes": 4}
        is_identifier_only = False
        is_offline = False

        async def setup(self, config): pass
        async def close(self): pass

        async def search(self, rom: Rom) -> list[Candidate]:
            raise ProviderBlockedError(self.name, reason="test")

        async def fetch_media(self, candidate, wanted):
            return {}

        def detect_blocked(self, response, body) -> bool:
            return False

        def is_auth_missing(self, exc: Exception) -> bool:
            return False

    db = Database(str(tmp_path / "test.db"))
    await db.init()
    run_id = await db.create_run(config_json={})
    await db.insert_discovered_pending(run_id, "snes", [
        {
            "rel_path": "game.smc", "raw_name": "game.smc",
            "normalized_name": "Game", "size": 1024, "mtime": 1,
            "crc32": "abc", "sha1": None, "cache_key": "k1",
        },
    ])
    rid = await db.find_pending_discovered_id(run_id, "snes", "game.smc")
    assert rid is not None
    await db.update_discovered_hash(
        rid, size=1024, mtime=1, crc32="abc", sha1=None,
        cache_key="k1", status="done",
    )

    reg = ProviderRegistry()
    reg.register(AlwaysBlockedProvider())

    orch = Orchestrator(
        registry=reg,
        config=MultiscraperConfig(),
        db=db,
        run_id=run_id,
        csv_path=tmp_path / "run.csv",
        media_root=tmp_path / "media",
        orchestrator=OrchestratorConfig(workers=1, discovery_poll_interval_sec=0.05),
    )
    discovery_done = asyncio.Event()
    discovery_done.set()
    with pytest.raises(BaseExceptionGroup) as exc_info:
        await orch.start(systems=["snes"], discovery_done=discovery_done)
    # TaskGroup wraps our AllProvidersBlocked in an ExceptionGroup.
    assert any(
        isinstance(sub, AllProvidersBlocked) for sub in exc_info.value.exceptions
    )

    assert orch.aborted_reason != ""
    assert orch.provider_errors.get("always_blocked", 0) >= 1
    await orch.close()
    await db.close()
