"""Tests for gamelist.xml generator."""

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from multiscraper.models import (
    GameMetadata,
    IdentifyMethod,
    MediaFile,
    MediaType,
    Rom,
    RomIdentifier,
    ScrapedResult,
    ScrapeStatus,
)
from multiscraper.output.gamelist_xml import generate_gamelist


def _make_result(
    name: str = "Test Game",
    status: ScrapeStatus = ScrapeStatus.OK,
    with_media: bool = True,
) -> ScrapedResult:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    media: list[MediaFile] = []
    if with_media:
        media = [
            MediaFile(type=MediaType.IMAGE, local_path="snes/Test-image.jpg",
                      ext="jpg", bytes=50000, sha256="a"*64, source="screenscraper"),
            MediaFile(type=MediaType.VIDEO, local_path="snes/Test-video.mp4",
                      ext="mp4", bytes=5000000, sha256="b"*64, source="screenscraper"),
        ]
    return ScrapedResult(
        rom=rom,
        status=status,
        identify_method=IdentifyMethod.CRC32,
        chosen_provider="screenscraper",
        match_score=0.95,
        metadata=GameMetadata(
            name=name,
            desc="A test game.",
            releasedate=datetime(1990, 8, 23, tzinfo=UTC),
            developer="Nintendo",
            publisher="Nintendo",
            genre="Platform",
            players=1,
            rating=0.95,
        ),
        media=media,
        fetched_at=datetime.now(tz=UTC),
    )


def test_generate_gamelist_basic() -> None:
    results = [_make_result()]
    xml = generate_gamelist(results, "snes")
    root = ET.fromstring(xml)
    assert root.tag == "gameList"
    games = root.findall("game")
    assert len(games) == 1
    game = games[0]
    assert game.find("path") is not None
    assert game.find("path").text == "./snes/test.smc"
    assert game.find("name") is not None
    assert game.find("name").text == "Test Game"
    assert game.find("desc") is not None
    assert game.find("desc").text == "A test game."
    assert game.find("developer") is not None
    assert game.find("developer").text == "Nintendo"
    assert game.find("genre") is not None
    assert game.find("genre").text == "Platform"
    assert game.find("rating") is not None
    assert game.find("rating").text == "0.95"
    assert game.find("releasedate") is not None
    assert game.find("releasedate").text == "19900823T000000"
    assert game.find("image") is not None
    assert game.find("image").text is not None
    assert game.find("video") is not None
    assert game.find("video").text is not None


def test_generate_gamelist_no_match_includes_path_only() -> None:
    ri = RomIdentifier(
        rel_path="./snes/mystery.rom", size=100, mtime=1000, cache_key="k2",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="mystery.rom", normalized_name="Mystery")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.NO_MATCH,
        identify_method=IdentifyMethod.NAME_ONLY,
        fetched_at=datetime.now(tz=UTC),
    )
    xml = generate_gamelist([result], "snes")
    root = ET.fromstring(xml)
    games = root.findall("game")
    assert len(games) == 1
    game = games[0]
    assert game.find("path") is not None
    assert game.find("path").text == "./snes/mystery.rom"
    assert game.find("name") is None
    assert game.find("desc") is None


def test_generate_gamelist_empty_tags_omitted() -> None:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=100, mtime=1000, cache_key="k3",
    )
    rom = Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test")
    result = ScrapedResult(
        rom=rom,
        status=ScrapeStatus.PARTIAL,
        identify_method=IdentifyMethod.CRC32,
        metadata=GameMetadata(name="Test"),
        fetched_at=datetime.now(tz=UTC),
    )
    xml = generate_gamelist([result], "snes")
    root = ET.fromstring(xml)
    game = root.find("game")
    assert game is not None
    name = game.find("name")
    assert name is not None
    assert name.text == "Test"
    assert game.find("desc") is None
    assert game.find("genre") is None


def test_generate_gamelist_multiple_games() -> None:
    results = [_make_result(name="Game 1"), _make_result(name="Game 2")]
    xml = generate_gamelist(results, "snes")
    root = ET.fromstring(xml)
    games = root.findall("game")
    assert len(games) == 2
    g0_name = games[0].find("name")
    assert g0_name is not None
    assert g0_name.text == "Game 1"
    g1_name = games[1].find("name")
    assert g1_name is not None
    assert g1_name.text == "Game 2"
