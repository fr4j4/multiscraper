"""Tests for ScreenScraper provider (mocked HTTP)."""

import logging
import re

import pytest
from aioresponses import aioresponses

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.screenscraper import ScreenScraperProvider

_SS_URL = re.compile(r"https://www\.screenscraper\.fr/api2/jeuInfos\.php.*")


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="Test.smc", normalized_name="Test")


@pytest.mark.asyncio
async def test_screenscraper_search_returns_candidates():
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test",
        "devpassword": "test",
        "region_priority": ["wor", "us"],
        "language_priority": ["en"],
    })

    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Data>
  <jeu>
    <id>123</id>
    <noms>
      <nom region="wor">Test Game</nom>
      <nom region="us">Test Game USA</nom>
    </noms>
    <synopsis>
      <synopsis langue="en">A test game description.</synopsis>
    </synopsis>
    <developpeur>TestDev</developpeur>
    <editeur>TestPub</editeur>
    <joueurs>1</joueurs>
    <genres>
      <genre langue="en">Action</genre>
    </genres>
    <dates>
      <date region="wor">1990-01-01</date>
    </dates>
    <medias>
      <media type="box2D" region="wor" format="png">https://example.com/box.png</media>
      <media type="ss" region="wor" format="jpg">https://example.com/ss.jpg</media>
      <media type="video" region="wor" format="mp4">https://example.com/vid.mp4</media>
    </medias>
  </jeu>
</Data>"""

    with aioresponses() as m:
        m.get(
            _SS_URL,
            status=200,
            body=xml_response,
            headers={"Content-Type": "application/xml"},
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates) == 1
    assert candidates[0].name == "Test Game"
    assert candidates[0].match_score > 0.5
    assert candidates[0].developer == "TestDev"
    assert candidates[0].description == "A test game description."

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_fetch_media():
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test",
        "devpassword": "test",
        "region_priority": ["wor"],
        "language_priority": ["en"],
    })

    xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Data>
  <jeu>
    <id>123</id>
    <noms><nom region="wor">Test Game</nom></noms>
    <medias>
      <media type="box2D" region="wor" format="png">https://example.com/box.png</media>
      <media type="video" region="wor" format="mp4">https://example.com/vid.mp4</media>
    </medias>
  </jeu>
</Data>"""

    with aioresponses() as m:
        m.get(
            _SS_URL,
            status=200,
            body=xml_response,
        )
        rom = _make_rom()
        candidates = await provider.search(rom)

    assert len(candidates[0].media) >= 1
    media_types = {m.type for m in candidates[0].media}
    assert MediaType.IMAGE in media_types or MediaType.VIDEO in media_types

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_detect_blocked():
    provider = ScreenScraperProvider()
    await provider.setup({"devid": "test", "devpassword": "test"})

    class FakeResp:
        status: int = 403

    assert provider.detect_blocked(FakeResp(), b"<html>cloudflare</html>") is True
    assert provider.detect_blocked(FakeResp(), b"<html>normal</html>") is False

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_logs_http_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When screenscraper returns a non-blocked error, log a warning."""
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    with aioresponses() as m:
        m.get(
            _SS_URL,
            status=500,
            body=b"<html>Internal Server Error</html>",
        )
        with caplog.at_level(
            logging.WARNING, logger="multiscraper.providers.screenscraper",
        ):
            candidates = await provider.search(_make_rom())

    assert candidates == []
    assert any(
        "screenscraper_http_error" in r.message
        and "status=500" in r.message
        for r in caplog.records
    ), f"expected warning, got: {[r.message for r in caplog.records]}"

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_logs_blocked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When screenscraper returns Cloudflare content, log + raise."""
    from multiscraper.providers.base import ProviderBlockedError

    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    with aioresponses() as m:
        m.get(
            _SS_URL,
            status=403,
            body=b"<html>cloudflare challenge</html>",
        )
        with caplog.at_level(
            logging.WARNING, logger="multiscraper.providers.screenscraper",
        ):
            with pytest.raises(ProviderBlockedError) as exc_info:
                await provider.search(_make_rom())
        assert exc_info.value.provider_name == "screenscraper"
        assert "cloudflare" in exc_info.value.reason

    assert any(
        "screenscraper_blocked" in r.message
        and "status=403" in r.message
        for r in caplog.records
    ), f"expected warning, got: {[r.message for r in caplog.records]}"

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_raises_on_429(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When screenscraper returns 429, raise ProviderBlockedError."""
    from multiscraper.providers.base import ProviderBlockedError

    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    with aioresponses() as m:
        m.get(_SS_URL, status=429, body=b"")
        with caplog.at_level(
            logging.WARNING, logger="multiscraper.providers.screenscraper",
        ):
            with pytest.raises(ProviderBlockedError) as exc_info:
                await provider.search(_make_rom())
        # 429 alone is a block signal in block_detect, so the reason
        # is `cloudflare_or_captcha` rather than `http_429`. Either is
        # fine — the important thing is that we raise.
        assert exc_info.value.provider_name == "screenscraper"

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_raises_on_430(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When screenscraper returns 430 (ScreenScraper quota), raise."""
    from multiscraper.providers.base import ProviderBlockedError

    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    with aioresponses() as m:
        m.get(
            _SS_URL,
            status=430,
            body=b"Votre quota de scrape est d\xc3\xa9pass\xc3\xa9 pour aujourd'hui !",
        )
        with caplog.at_level(
            logging.WARNING, logger="multiscraper.providers.screenscraper",
        ):
            with pytest.raises(ProviderBlockedError) as exc_info:
                await provider.search(_make_rom())
        assert exc_info.value.reason == "http_430"

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_raises_on_503(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When screenscraper returns 503, raise ProviderBlockedError."""
    from multiscraper.providers.base import ProviderBlockedError

    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    with aioresponses() as m:
        m.get(_SS_URL, status=503, body=b"")
        with pytest.raises(ProviderBlockedError) as exc_info:
            await provider.search(_make_rom())
        assert exc_info.value.reason == "http_503"

    await provider.close()


@pytest.mark.asyncio
async def test_screenscraper_logs_no_match(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = ScreenScraperProvider()
    await provider.setup({
        "devid": "test", "devpassword": "test",
        "region_priority": ["wor"], "language_priority": ["en"],
    })

    xml_empty = b"""<?xml version="1.0" encoding="UTF-8"?>
<Data></Data>"""

    with aioresponses() as m:
        m.get(_SS_URL, status=200, body=xml_empty)
        with caplog.at_level(
            logging.INFO, logger="multiscraper.providers.screenscraper",
        ):
            candidates = await provider.search(_make_rom())

    assert candidates == []
    assert any(
        "screenscraper_no_match" in r.message for r in caplog.records
    ), f"expected info log, got: {[r.message for r in caplog.records]}"

    await provider.close()
