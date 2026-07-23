"""Tests for multiscraper core models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from multiscraper.models import (
    Candidate,
    GameMetadata,
    IdentifyMethod,
    MediaFile,
    MediaRef,
    MediaType,
    Rom,
    RomIdentifier,
    RunReport,
    RunTotals,
    ScrapedResult,
    ScrapeStatus,
)


def test_media_type_values():
    assert MediaType.IMAGE == "image"
    assert MediaType.VIDEO == "video"
    assert MediaType.MARQUEE == "marquee"
    assert MediaType.BOX3D == "box3d"
    assert MediaType.LOGO == "logo"


def test_scrape_status_values():
    assert ScrapeStatus.OK == "OK"
    assert ScrapeStatus.PARTIAL == "PARTIAL"
    assert ScrapeStatus.NO_MATCH == "NO_MATCH"
    assert ScrapeStatus.TIMED_OUT == "TIMED_OUT"
    assert ScrapeStatus.SKIPPED == "SKIPPED"


def test_identify_method_values():
    assert IdentifyMethod.CRC32 == "crc32"
    assert IdentifyMethod.SHA1 == "sha1"
    assert IdentifyMethod.NAME_ONLY == "name_only"
    assert IdentifyMethod.HASHEOUS == "hasheous"


def test_rom_identifier_cache_key_required():
    with pytest.raises(ValidationError):
        RomIdentifier(rel_path="./foo.smc", size=100, mtime=1000)


def test_rom_identifier_valid():
    ri = RomIdentifier(
        rel_path="./snes/foo.smc",
        size=524288,
        mtime=1700000000,
        crc32="ab12cd34",
        cache_key="abc123",
    )
    assert ri.crc32 == "ab12cd34"
    assert ri.sha1 is None


def test_rom_valid():
    ri = RomIdentifier(
        rel_path="./snes/foo.smc",
        size=100,
        mtime=1000,
        cache_key="key1",
    )
    rom = Rom(
        system="snes",
        rom_id=ri,
        raw_name="Foo (USA).smc",
        normalized_name="Foo",
    )
    assert rom.system == "snes"
    assert rom.normalized_name == "Foo"
    assert rom.preferred_region == "wor"
    assert rom.preferred_language == "en"


def test_media_ref_valid():
    mr = MediaRef(
        type=MediaType.IMAGE,
        url="https://example.com/img.jpg",
        ext="jpg",
        source="screenscraper",
    )
    assert mr.type == MediaType.IMAGE
    assert mr.ext == "jpg"


def test_candidate_match_score_bounds():
    with pytest.raises(ValidationError):
        Candidate(
            provider="test",
            source_id="1",
            name="Test",
            match_score=1.5,
        )
    with pytest.raises(ValidationError):
        Candidate(
            provider="test",
            source_id="1",
            name="Test",
            match_score=-0.1,
        )


def test_candidate_valid():
    c = Candidate(
        provider="screenscraper",
        source_id="123",
        name="Super Mario World",
        match_score=0.95,
    )
    assert c.match_score == 0.95
    assert c.media == []


def test_game_metadata_defaults():
    gm = GameMetadata(name="Test Game")
    assert gm.desc is None
    assert gm.rating is None
    assert gm.players is None


def test_media_file_valid():
    mf = MediaFile(
        type=MediaType.IMAGE,
        local_path="snes/Foo-image.jpg",
        ext="jpg",
        bytes=1024,
        sha256="a" * 64,
        source="screenscraper",
    )
    assert mf.bytes == 1024


def test_scraped_result_valid():
    ri = RomIdentifier(rel_path="./snes/foo.smc", size=100, mtime=1000, cache_key="k")
    rom = Rom(system="snes", rom_id=ri, raw_name="foo.smc", normalized_name="Foo")
    sr = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.OK,
        identify_method=IdentifyMethod.CRC32,
        fetched_at=datetime.now(tz=UTC),
    )
    assert sr.status == ScrapeStatus.OK
    assert sr.media == []
    assert sr.warnings == []


def test_run_totals_defaults():
    rt = RunTotals()
    assert rt.roms_total == 0
    assert rt.roms_ok == 0
    assert rt.media_files_downloaded == 0


def test_run_report_valid():
    rr = RunReport(
        run_id="01HTEST",
        started_at=datetime.now(tz=UTC),
        config_snapshot={},
    )
    assert rr.status == "running"
    assert rr.totals.roms_total == 0
