# Adding a Provider

A "provider" in `multiscraper` is any data source that can answer
two questions about a ROM:

1. **Search** — given a `Rom`, return a list of `Candidate`s with
   `match_score`, metadata, and `MediaRef` URLs.
2. **Fetch media** — given a chosen `Candidate` and a set of wanted
   `MediaType` values, return the URLs of the corresponding media
   files (still hosted at the provider; the worker downloads them).

Some sources are **identifier-only** (e.g. `Hasheous`): they only
answer "given a hash, what is the canonical name of this game?".
They implement the `Identifier` Protocol instead.

This document covers the Protocol, the steps to add a new provider,
and how to test it.

## The `Provider` Protocol

Defined in `src/multiscraper/providers/base.py` (with `@runtime_checkable`
so `isinstance(p, Provider)` works).

```python
@runtime_checkable
class Provider(Protocol):
    name: str
    requires_auth: bool
    auth_fields: list[str]
    rate_limit_per_sec: float
    priority: int
    supported_media: set[MediaType]
    platform_map: dict[str, str | int]
    is_identifier_only: bool
    is_offline: bool

    async def setup(self, config: dict[str, object]) -> None: ...
    async def close(self) -> None: ...
    async def search(self, rom: Rom) -> list[Candidate]: ...
    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]: ...
    def detect_blocked(self, response: object, body: bytes) -> bool: ...
    def is_auth_missing(self, exc: Exception) -> bool: ...
```

### Field reference

| Field | Type | Meaning |
|---|---|---|
| `name` | str | Unique registry key (also used as the `id` in `sources.yaml`). |
| `requires_auth` | bool | If true, `setup()` will fail without the fields in `auth_fields`. |
| `auth_fields` | list[str] | Names of the keys expected in the per-provider `config:` block. |
| `rate_limit_per_sec` | float | Token-bucket refill rate. |
| `priority` | int | Lower runs first in the cascade. |
| `supported_media` | set[MediaType] | Subset of `MediaType` (image, thumbnail, video, marquee, box3d, backcover, fanart, manual, miximage, logo). |
| `platform_map` | dict[str, str \| int] | Map from multiscraper system name to the provider's platform id. |
| `is_identifier_only` | bool | If true, the provider is treated as an `Identifier`. |
| `is_offline` | bool | If true, the provider never makes network calls. |

### Method reference

- `async setup(config)` — called once at startup. Open the
  `aiohttp.ClientSession`, validate credentials. Empty `config={}` is
  legal. Should raise `AuthMissingError` if `requires_auth` and the
  required fields are missing.
- `async close()` — release resources. Called on graceful shutdown.
- `async search(rom)` — return 0+ `Candidate`s. Each `Candidate` must
  have a `match_score` between `0.0` and `1.0`. The cascade will
  discard candidates below `provider_defaults.match_threshold` (0.7
  default). Return at most `max_candidates_per_provider` items.
- `async fetch_media(candidate, wanted)` — return a dict from each
  `MediaType` you can serve to a `MediaRef`. Only types that appear in
  both `wanted` and `supported_media` are expected to be returned.
  URLs must be absolute. If you cannot serve a requested type,
  simply omit it from the returned dict; the cascade will fall
  through to the next provider.
- `detect_blocked(response, body)` — return `True` if the response
  looks like a Cloudflare challenge, captcha, or 429. The cascade
  will mark the provider as blocked and skip it for
  `cooldown_after_blocked_sec`. The default detector is in
  `providers/block_detect.py`.
- `is_auth_missing(exc)` — return `True` if the exception indicates
  the provider is unauthenticated. The cascade will permanently
  disable the provider for the run.

## The `Identifier` Protocol

```python
@runtime_checkable
class Identifier(Protocol):
    name: str
    async def identify(self, rom: Rom) -> IdentifierResult | None: ...

class IdentifierResult(BaseModel):
    canonical_name: str
    platform: str
    source_id: str
    provider: str
    confidence: float = 1.0
```

`Identifier.identify` is called only when the media cascade failed
to find a match. The result's `canonical_name` is used to re-run
the cascade with a better query string.

## Step-by-step: add a new provider

### 1. Create the module

Pick a short, unique name. Place the file in
`src/multiscraper/providers/<name>.py`.

```python
# src/multiscraper/providers/myprovider.py
from __future__ import annotations

from typing import Any, ClassVar

import aiohttp
from pydantic import HttpUrl

from multiscraper.models import Candidate, MediaRef, MediaType, Rom
from multiscraper.providers.block_detect import detect_blocked


class MyProvider:
    """One-line description of the source."""

    name: ClassVar[str] = "myprovider"
    requires_auth: ClassVar[bool] = True
    auth_fields: ClassVar[list[str]] = ["api_key"]
    rate_limit_per_sec: ClassVar[float] = 2.0
    priority: ClassVar[int] = 60
    supported_media: ClassVar[set[MediaType]] = {
        MediaType.IMAGE, MediaType.THUMBNAIL,
    }
    platform_map: ClassVar[dict[str, str | int]] = {
        "snes": "snes", "psx": "ps1",
    }
    is_identifier_only: ClassVar[bool] = False
    is_offline: ClassVar[bool] = False

    def __init__(self) -> None:
        self._api_key: str = ""
        self._session: aiohttp.ClientSession | None = None

    async def setup(self, config: dict[str, Any]) -> None:
        self._api_key = str(config.get("api_key", ""))
        if not self._api_key:
            from multiscraper.core.errors import AuthMissingError
            raise AuthMissingError("myprovider: api_key missing")
        self._session = aiohttp.ClientSession(
            headers={"X-Api-Key": self._api_key},
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, rom: Rom) -> list[Candidate]:
        assert self._session is not None
        url = "https://api.myprovider.com/search"
        params = {"q": rom.normalized_name}
        async with self._session.get(url, params=params) as resp:
            if detect_blocked(resp, await resp.read()):
                from multiscraper.core.errors import BlockedError
                raise BlockedError("myprovider: blocked")
            data = await resp.json()
        out: list[Candidate] = []
        for item in data.get("results", [])[:10]:
            out.append(Candidate(
                provider=self.name,
                source_id=str(item["id"]),
                name=item["title"],
                match_score=item.get("score", 0.5),
                releasedate=None,
                developer=item.get("developer"),
                publisher=item.get("publisher"),
                genre=item.get("genre"),
                players=item.get("players"),
                rating=item.get("rating"),
                description=item.get("summary"),
                media=[],
            ))
        return out

    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]:
        if self._session is None:
            return {}
        result: dict[MediaType, MediaRef] = {}
        async with self._session.get(
            f"https://api.myprovider.com/game/{candidate.source_id}/media"
        ) as resp:
            data = await resp.json()
        if MediaType.IMAGE in wanted and data.get("cover_url"):
            result[MediaType.IMAGE] = MediaRef(
                type=MediaType.IMAGE,
                url=HttpUrl(data["cover_url"]),
                ext="jpg",
                source=self.name,
            )
        if MediaType.THUMBNAIL in wanted and data.get("thumb_url"):
            result[MediaType.THUMBNAIL] = MediaRef(
                type=MediaType.THUMBNAIL,
                url=HttpUrl(data["thumb_url"]),
                ext="jpg",
                source=self.name,
            )
        return result

    def detect_blocked(self, response: object, body: bytes) -> bool:
        return detect_blocked(response, body)

    def is_auth_missing(self, exc: Exception) -> bool:
        from multiscraper.core.errors import AuthMissingError
        return isinstance(exc, AuthMissingError)


assert isinstance(MyProvider(), Provider)
```

A few notes on the example:

- `priority: 60` slots between `thegamesdb` (35) and `libretro_thumbnails`
  (40) ... adjust as needed.
- `platform_map` is consulted by the cascade when it knows which
  provider-specific platform id to pass.
- The `assert isinstance(..., Provider)` at the bottom is a
  development-time check; the Protocol is structural, so it will
  fail at import if a field or method is missing.

### 2. Register in `sources.yaml`

```yaml
providers:
  - id: myprovider
    priority: 60
    enabled: true
    config:
      api_key: ${env:MYPROVIDER_API_KEY}
```

If the field is missing or empty, the loader's Pydantic validation
will not catch it (Pydantic does not see provider-level config).
`setup()` must raise `AuthMissingError` instead.

### 3. (Optional) Register an entry point

Third-party packages can ship providers without forking the repo. In
your package's `pyproject.toml`:

```toml
[project.entry-points."multiscraper.providers"]
myprovider = "myprovider_pkg:MyProvider"
```

`ProviderRegistry` reads this entry-point group and registers any
class that satisfies the `Provider` Protocol. The name is the
registered `Provider.name`, not the entry-point key.

### 4. Write tests

The unit tests should mock the network. Two recommended approaches:

**`aioresponses`** — drop-in `aiohttp` mock.

```python
import aiohttp
import pytest
from aioresponses import aioresponses

from multiscraper.models import Rom, RomIdentifier
from multiscraper.providers.myprovider import MyProvider


@pytest.mark.asyncio
async def test_search_returns_candidate() -> None:
    provider = MyProvider()
    await provider.setup({"api_key": "test-key"})

    rom = Rom(
        system="snes",
        rom_id=RomIdentifier(
            rel_path="./roms/Super Mario World.smc",
            size=524288, mtime=1700000000,
            crc32="deadbeef", sha1=None, cache_key="abc",
        ),
        raw_name="Super Mario World (USA).smc",
        normalized_name="Super Mario World",
    )

    with aioresponses() as m:
        m.get(
            "https://api.myprovider.com/search",
            payload={"results": [{
                "id": 1, "title": "Super Mario World", "score": 0.95,
            }]},
        )
        cands = await provider.search(rom)

    assert len(cands) == 1
    assert cands[0].name == "Super Mario World"
    assert cands[0].match_score == 0.95

    await provider.close()
```

**`vcrpy`** — record real responses once, replay from cassette.

```python
import vcr

from multiscraper.providers.myprovider import MyProvider

my_vcr = vcr.VCR(
    cassette_library_dir="tests/cassettes/myprovider",
    record_mode="once",
    match_on=["method", "scheme", "host", "port", "path", "query"],
)


@my_vcr.use_cassette("search_success.yaml")
@pytest.mark.asyncio
async def test_search_replay() -> None:
    provider = MyProvider()
    await provider.setup({"api_key": "test-key"})
    cands = await provider.search(make_rom())
    assert cands
    await provider.close()
```

Cassettes live in `tests/cassettes/<provider>/<test>.yaml`. Mark
recordings with `@pytest.mark.network` so they can be skipped in CI.
The CI command is `pytest -m "not network" -m "not slow"` (see spec
Sección 6.6).

### 5. Match scoring

The cascade uses `compute_match_score` in
`providers/match.py`. Your `Candidate.match_score` is the main
signal. A good rule of thumb:

- `0.95+` for an exact normalized-name match.
- `0.85` for a name match with a small typo or trailing region tag.
- `0.70` (the default `match_threshold`) for a plausible fuzzy match.
- Below `0.50` the cascade will reject it.

If the provider returns its own confidence score, map it into this
range and use it. If the score is absent, default to `0.5` and let
the user raise `match_threshold` if they want stricter matching.

## Common pitfalls

- **Absolute URLs only.** `MediaRef.url` is a Pydantic `HttpUrl` and
  must be parseable. A bare path will be rejected.
- **Respect `wanted`.** The cascade passes you a `set[MediaType]`
  containing only types the user opted into. Skip the rest.
- **Don't swallow exceptions.** Let `BlockedError`, `AuthMissingError`,
  and `RateLimitError` propagate. The cascade relies on them.
- **No background tasks in `setup`.** The `aiohttp.ClientSession`
  must be created on the running event loop. Don't call
  `asyncio.get_event_loop().create_task` from `setup()`.
- **Be polite.** Stick to `rate_limit_per_sec` and the per-provider
  cooldown. The cascade will block you automatically when you trip
  the detector, but a polite provider avoids the cold start.
