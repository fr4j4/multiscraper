# Phase 4: Providers Core (Protocol, Registry, Match, Cascade)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `Provider` Protocol, `Identifier` Protocol, `ProviderRegistry`, match scoring, cascade logic, and block detection. These are the core abstractions that all 13 providers implement.

**Depends on:** Phase 1 (models, utils), Phase 2 (config), Phase 3 (output/db).

**Milestone:** Cascade logic unit tests pass with `FakeProvider`; match scoring tests pass; block detection tests pass; `ruff` and `mypy` pass.

**Parallelizable:** Partially. Task 4.1 (Protocol + registry) must be first. Then 4.2 (match), 4.3 (block_detect), 4.4 (cascade) can be parallelized.

---

## Task 4.1: Provider Protocol, Identifier Protocol, and ProviderRegistry

**Files:**
- Create: `src/multiscraper/providers/__init__.py`
- Create: `src/multiscraper/providers/base.py`
- Create: `src/multiscraper/providers/registry.py`
- Test: `tests/unit/test_registry.py`

**Interfaces:**
- Produces: `Provider` (Protocol), `Identifier` (Protocol), `IdentifierResult` (model), `ProviderRegistry`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_registry.py
"""Tests for ProviderRegistry."""

import pytest

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.base import IdentifierResult
from multiscraper.providers.registry import ProviderRegistry


class FakeProvider:
    name = "fake"
    requires_auth = False
    auth_fields: list[str] = []
    rate_limit_per_sec = 2.0
    priority = 5
    supported_media = {MediaType.IMAGE, MediaType.VIDEO}
    platform_map: dict[str, str | int] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict) -> None: pass
    async def close(self) -> None: pass
    async def search(self, rom: Rom) -> list: return []
    async def fetch_media(self, candidate, wanted): return {}
    def detect_blocked(self, response, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


class FakeIdentifier:
    name = "fake_ident"

    async def identify(self, rom: Rom) -> IdentifierResult | None:
        return None


def test_registry_register_provider():
    reg = ProviderRegistry()
    p = FakeProvider()
    reg.register(p)
    assert reg.get("fake") is p


def test_registry_providers_for_media():
    reg = ProviderRegistry()
    reg.register(FakeProvider())
    providers = reg.providers_for_media(MediaType.IMAGE)
    assert len(providers) == 1
    assert providers[0].name == "fake"


def test_registry_providers_for_media_empty():
    reg = ProviderRegistry()
    providers = reg.providers_for_media(MediaType.MANQUEE)
    assert len(providers) == 0


def test_registry_sorted_by_priority():
    class HighPriority(FakeProvider):
        name = "high"
        priority = 1
    class LowPriority(FakeProvider):
        name = "low"
        priority = 100

    reg = ProviderRegistry()
    reg.register(LowPriority())
    reg.register(HighPriority())
    providers = reg.providers_for_media(MediaType.IMAGE)
    assert providers[0].name == "high"
    assert providers[1].name == "low"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/providers/__init__.py
```

```python
# src/multiscraper/providers/base.py
"""Provider and Identifier Protocols for multiscraper.

Every data source implements the Provider Protocol. Identifier-only
sources (like Hasheous) implement the Identifier Protocol instead.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from multiscraper.models import Candidate, MediaRef, MediaType, Rom


@runtime_checkable
class Provider(Protocol):
    """Interface for every media/data provider."""

    name: str
    requires_auth: bool
    auth_fields: list[str]
    rate_limit_per_sec: float
    priority: int
    supported_media: set[MediaType]
    platform_map: dict[str, str | int]
    is_identifier_only: bool
    is_offline: bool

    async def setup(self, config: dict) -> None: ...
    async def close(self) -> None: ...
    async def search(self, rom: Rom) -> list[Candidate]: ...
    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType],
    ) -> dict[MediaType, MediaRef]: ...
    def detect_blocked(self, response: object, body: bytes) -> bool: ...
    def is_auth_missing(self, exc: Exception) -> bool: ...


class IdentifierResult(BaseModel):
    """Result from an identifier provider (hash → name lookup)."""

    canonical_name: str
    platform: str
    source_id: str
    provider: str
    confidence: float = 1.0


@runtime_checkable
class Identifier(Protocol):
    """Interface for identifier-only providers (hash resolvers)."""

    name: str

    async def identify(self, rom: Rom) -> IdentifierResult | None: ...
```

```python
# src/multiscraper/providers/registry.py
"""ProviderRegistry: auto-discovery and lookup of providers by media type."""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol, runtime_checkable

from multiscraper.models import MediaType
from multiscraper.providers.base import Identifier, Provider


class ProviderRegistry:
    """Registry of all available providers, indexed by name and media type."""

    def __init__(self) -> None:
        self._by_name: dict[str, Provider] = {}
        self._by_media_type: dict[MediaType, list[Provider]] = defaultdict(list)
        self._identifiers: list[Identifier] = []

    def register(self, provider: Provider) -> None:
        """Register a provider. Must have a unique name."""
        self._by_name[provider.name] = provider
        for mt in provider.supported_media:
            self._by_media_type[mt].append(provider)
        # Check if it's also an Identifier
        if hasattr(provider, "identify") and callable(getattr(provider, "identify")):
            self._identifiers.append(provider)  # type: ignore[arg-type]

    def get(self, name: str) -> Provider | None:
        """Get a provider by name."""
        return self._by_name.get(name)

    def providers_for_media(self, mt: MediaType) -> list[Provider]:
        """Get all providers that offer this media type, sorted by priority."""
        return sorted(self._by_media_type.get(mt, []), key=lambda p: p.priority)

    @property
    def identifiers(self) -> list[Identifier]:
        """All registered identifier providers."""
        return self._identifiers

    @property
    def all_providers(self) -> list[Provider]:
        """All registered providers, sorted by priority."""
        return sorted(self._by_name.values(), key=lambda p: p.priority)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/providers/__init__.py src/multiscraper/providers/base.py src/multiscraper/providers/registry.py tests/unit/test_registry.py
git commit -m "feat: add Provider/Identifier Protocols and ProviderRegistry"
```

---

## Task 4.2: Match scoring

**Files:**
- Create: `src/multiscraper/providers/match.py`
- Test: `tests/unit/test_match.py`

**Interfaces:**
- Produces: `compute_match_score(rom_name: str, candidate_name: str) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_match.py
"""Tests for match scoring."""

import pytest

from multiscraper.providers.match import compute_match_score


def test_exact_match():
    assert compute_match_score("Super Mario World", "Super Mario World") == 1.0


def test_case_insensitive_match():
    assert compute_match_score("super mario world", "Super Mario World") == 1.0


def test_partial_match():
    score = compute_match_score("Super Mario World", "Super Mario World 2")
    assert 0.5 < score < 1.0


def test_no_match():
    score = compute_match_score("Super Mario World", "Final Fantasy")
    assert score < 0.3


def test_empty_strings():
    assert compute_match_score("", "") == 0.0


def test_subtitle_match():
    score = compute_match_score("Super Mario World", "Super Mario World: The Lost Levels")
    assert score > 0.7


def test_the_removal():
    score = compute_match_score("Legend of Zelda", "The Legend of Zelda")
    assert score > 0.9
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_match.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/providers/match.py
"""Match scoring between ROM names and candidate game names.

Uses a combination of normalized string similarity (difflib SequenceMatcher)
and heuristics (article removal, case folding).
"""

from __future__ import annotations

from difflib import SequenceMatcher


def _normalize(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip articles, collapse spaces."""
    result = name.lower().strip()
    # Remove leading articles
    for article in ("the ", "a ", "an "):
        if result.startswith(article):
            result = result[len(article):]
    # Collapse whitespace
    result = " ".join(result.split())
    return result


def compute_match_score(rom_name: str, candidate_name: str) -> float:
    """Compute a match score between a ROM name and a candidate game name.

    Args:
        rom_name: Normalized ROM name (from normalize_rom_name).
        candidate_name: Game name from a provider.

    Returns:
        Score between 0.0 (no match) and 1.0 (exact match).
    """
    if not rom_name or not candidate_name:
        return 0.0

    norm_rom = _normalize(rom_name)
    norm_cand = _normalize(candidate_name)

    if norm_rom == norm_cand:
        return 1.0

    # If candidate contains the full rom name (subtitle case)
    if norm_rom in norm_cand:
        ratio = len(norm_rom) / len(norm_cand)
        return max(0.7, ratio)

    # If rom name contains the full candidate name
    if norm_cand in norm_rom:
        ratio = len(norm_cand) / len(norm_rom)
        return max(0.7, ratio)

    # Sequence similarity
    ratio = SequenceMatcher(None, norm_rom, norm_cand).ratio()
    return ratio
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_match.py -v
```

Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/providers/match.py tests/unit/test_match.py
git commit -m "feat: add match scoring with SequenceMatcher and heuristics"
```

---

## Task 4.3: Block detection (Cloudflare / captcha)

**Files:**
- Create: `src/multiscraper/providers/block_detect.py`
- Test: `tests/unit/test_block_detect.py`

**Interfaces:**
- Produces: `detect_blocked(status: int, body: bytes, headers: dict) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_block_detect.py
"""Tests for block detection."""

import pytest

from multiscraper.providers.block_detect import detect_blocked


def test_detect_cloudflare_403():
    body = b"<html><head><title>Just a moment...</title></head></html>"
    assert detect_blocked(403, body, {"cf-ray": "abc123"}) is True


def test_detect_cloudflare_503():
    body = b"Checking your browser before accessing.
    <script>cf_chl_opt</script>"
    assert detect_blocked(503, body, {}) is True


def test_detect_captcha():
    body = b"<html>Please complete the captcha to continue</html>"
    assert detect_blocked(403, body, {}) is True


def test_detect_challenge_page():
    body = b"<html>Checking your browser before accessing"
    assert detect_blocked(503, body, {}) is True


def test_no_block_200():
    body = b'<html><body>Normal page</body></html>'
    assert detect_blocked(200, body, {}) is False


def test_no_block_404():
    body = b'<html><body>Not Found</body></html>'
    assert detect_blocked(404, body, {}) is False


def test_detect_rate_limit_429():
    body = b'{"error": "rate limited"}'
    assert detect_blocked(429, body, {}) is True


def test_detect_cf_ray_header():
    body = b"some content"
    assert detect_blocked(403, body, {"cf-ray": "123456-LAX"}) is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_block_detect.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/providers/block_detect.py
"""Block detection for Cloudflare, captcha, and rate limiting.

Providers use this to determine if a response indicates the source
is blocking us (Cloudflare challenge, captcha, 429 rate limit).
"""

from __future__ import annotations


_BLOCKING_STATUSES = {403, 503, 429}

_BLOCK_SIGNALS = [
    b"cloudflare",
    b"cf-ray",
    b"cf_chl_opt",
    b"captcha",
    b"challenge",
    b"just a moment",
    b"checking your browser",
    b"are you human",
    b"ddg_captcha",
]


def detect_blocked(status: int, body: bytes, headers: dict[str, str]) -> bool:
    """Detect if a response indicates blocking (Cloudflare, captcha, rate limit).

    Args:
        status: HTTP status code.
        body: Response body (bytes).
        headers: Response headers.

    Returns:
        True if the response indicates blocking, False otherwise.
    """
    if status not in _BLOCKING_STATUSES:
        return False

    # Check headers for Cloudflare
    for key, val in headers.items():
        if key.lower() in ("cf-ray", "cf-mitigated"):
            return True

    # Check body for known block signals
    body_lower = body.lower()[:2000]  # only check first 2KB
    for signal in _BLOCK_SIGNALS:
        if signal in body_lower:
            return True

    # 429 is always a rate limit
    if status == 429:
        return True

    return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_block_detect.py -v
```

Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/providers/block_detect.py tests/unit/test_block_detect.py
git commit -m "feat: add block detection for Cloudflare, captcha, and rate limiting"
```

---

## Task 4.4: Cascade logic with FakeProvider

**Depends on:** Task 4.1 (registry), 4.2 (match), 4.3 (block_detect).

**Files:**
- Create: `src/multiscraper/providers/cascade.py`
- Test: `tests/unit/test_cascade.py`

**Interfaces:**
- Produces: `async def run_cascade(rom, registry, config, blocked_set) -> CascadeResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cascade.py
"""Tests for cascade logic with FakeProvider."""

from datetime import datetime, timezone

import pytest

from multiscraper.models import (
    Candidate, GameMetadata, IdentifyMethod, MediaRef, MediaType,
    Rom, RomIdentifier, ScrapeStatus,
)
from multiscraper.providers.base import IdentifierResult
from multiscraper.providers.cascade import CascadeResult, run_cascade
from multiscraper.providers.registry import ProviderRegistry


class FakeGoodProvider:
    """A provider that returns a high-quality match."""
    name = "good_provider"
    requires_auth = False
    auth_fields: list[str] = []
    rate_limit_per_sec = 10.0
    priority = 1
    supported_media = {MediaType.IMAGE}
    platform_map: dict[str, str | int] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict) -> None: pass
    async def close(self) -> None: pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return [Candidate(
            provider="good_provider", source_id="1",
            name=rom.normalized_name, match_score=0.95,
            description="A great game.",
        )]

    async def fetch_media(self, candidate: Candidate, wanted: set[MediaType]) -> dict[MediaType, MediaRef]:
        return {MediaType.IMAGE: MediaRef(
            type=MediaType.IMAGE, url="https://example.com/img.jpg",
            ext="jpg", source="good_provider",
        )}

    def detect_blocked(self, response: object, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


class FakeBadProvider:
    """A provider that returns a low-quality match."""
    name = "bad_provider"
    requires_auth = False
    auth_fields: list[str] = []
    rate_limit_per_sec = 10.0
    priority = 10
    supported_media = {MediaType.IMAGE}
    platform_map: dict[str, str | int] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict) -> None: pass
    async def close(self) -> None: pass

    async def search(self, rom: Rom) -> list[Candidate]:
        return [Candidate(
            provider="bad_provider", source_id="2",
            name="Wrong Game", match_score=0.3,
        )]

    async def fetch_media(self, candidate: Candidate, wanted: set[MediaType]) -> dict[MediaType, MediaRef]:
        return {}

    def detect_blocked(self, response: object, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


def _make_rom() -> Rom:
    ri = RomIdentifier(
        rel_path="./snes/test.smc", size=1024, mtime=1700000000,
        crc32="ab12cd34", cache_key="key1",
    )
    return Rom(system="snes", rom_id=ri, raw_name="test.smc", normalized_name="Test Game")


@pytest.mark.asyncio
async def test_cascade_picks_best_provider():
    reg = ProviderRegistry()
    reg.register(FakeBadProvider())
    reg.register(FakeGoodProvider())

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers=set(),
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.OK
    assert result.chosen_provider == "good_provider"
    assert result.match_score == 0.95


@pytest.mark.asyncio
async def test_cascade_no_match():
    reg = ProviderRegistry()
    reg.register(FakeBadProvider())  # only low-quality

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers=set(),
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.NO_MATCH


@pytest.mark.asyncio
async def test_cascade_all_blocked():
    reg = ProviderRegistry()
    reg.register(FakeGoodProvider())

    result = await run_cascade(
        rom=_make_rom(),
        registry=reg,
        match_threshold=0.7,
        blocked_providers={"good_provider"},
        wanted_media={MediaType.IMAGE},
    )
    assert result.status == ScrapeStatus.BLOCKED
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_cascade.py -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/multiscraper/providers/cascade.py
"""Cascade logic: try providers in priority order, pick best match.

The cascade has two phases:
1. Identification: search by name, pick best candidate above threshold.
2. Media: for each wanted media type, try providers in priority order.
"""

from __future__ import annotations

from datetime import datetime, timezone

from multiscraper.models import (
    Candidate, GameMetadata, IdentifyMethod, MediaRef, MediaType,
    Rom, ScrapedResult, ScrapeStatus,
)
from multiscraper.providers.registry import ProviderRegistry


class CascadeResult:
    """Internal result from run_cascade, wrapped into ScrapedResult."""

    def __init__(self, status: ScrapeStatus, chosen: Candidate | None = None,
                 media: dict[MediaType, MediaRef] | None = None,
                 identify_method: IdentifyMethod = IdentifyMethod.NAME_ONLY):
        self.status = status
        self.chosen = chosen
        self.media = media or {}
        self.identify_method = identify_method

    def to_scraped_result(self, rom: Rom) -> ScrapedResult:
        md = None
        chosen_provider = None
        match_score = None
        if self.chosen:
            md = GameMetadata(
                name=self.chosen.name,
                desc=self.chosen.description,
                releasedate=self.chosen.releasedate,
                developer=self.chosen.developer,
                publisher=self.chosen.publisher,
                genre=self.chosen.genre,
                players=self.chosen.players,
                rating=self.chosen.rating,
            )
            chosen_provider = self.chosen.provider
            match_score = self.chosen.match_score
        return ScrapedResult(
            rom=rom,
            status=self.status,
            identify_method=self.identify_method,
            chosen_provider=chosen_provider,
            match_score=match_score,
            metadata=md,
            fetched_at=datetime.now(tz=timezone.utc),
        )


async def run_cascade(
    rom: Rom,
    registry: ProviderRegistry,
    match_threshold: float,
    blocked_providers: set[str],
    wanted_media: set[MediaType],
) -> ScrapedResult:
    """Run the provider cascade for a single ROM.

    Args:
        rom: The ROM to scrape.
        registry: Provider registry with all providers.
        match_threshold: Minimum match score to accept.
        blocked_providers: Set of provider names currently blocked.
        wanted_media: Set of media types to fetch.

    Returns:
        ScrapedResult with status OK, PARTIAL, NO_MATCH, or BLOCKED.
    """
    all_providers = registry.all_providers
    available = [p for p in all_providers if p.name not in blocked_providers]

    if not available:
        return ScrapedResult(
            rom=rom, status=ScrapeStatus.BLOCKED,
            identify_method=IdentifyMethod.NAME_ONLY,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    # Phase 1: Identification — search by name
    best_candidate: Candidate | None = None
    for provider in available:
        if provider.is_identifier_only:
            continue
        try:
            candidates = await provider.search(rom)
        except Exception:
            continue
        for cand in candidates:
            if best_candidate is None or cand.match_score > best_candidate.match_score:
                best_candidate = cand
        if best_candidate and best_candidate.match_score >= match_threshold:
            break

    if best_candidate is None or best_candidate.match_score < match_threshold:
        return ScrapedResult(
            rom=rom, status=ScrapeStatus.NO_MATCH,
            identify_method=IdentifyMethod.NAME_ONLY,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    # Phase 2: Media — for each wanted type, try providers in priority order
    media: dict[MediaType, MediaRef] = {}
    for mt in wanted_media:
        for provider in available:
            if provider.is_identifier_only:
                continue
            if mt not in provider.supported_media:
                continue
            try:
                refs = await provider.fetch_media(best_candidate, {mt})
                if mt in refs:
                    media[mt] = refs[mt]
                    break
            except Exception:
                continue

    # Determine status: OK if image present and enough media, PARTIAL otherwise
    has_image = MediaType.IMAGE in media
    if has_image and len(media) >= 3:
        status = ScrapeStatus.OK
    elif len(media) > 0:
        status = ScrapeStatus.PARTIAL
    else:
        status = ScrapeStatus.PARTIAL  # metadata without media is still partial

    return ScrapedResult(
        rom=rom,
        status=status,
        identify_method=IdentifyMethod.NAME_ONLY,
        chosen_provider=best_candidate.provider,
        match_score=best_candidate.match_score,
        metadata=GameMetadata(
            name=best_candidate.name,
            desc=best_candidate.description,
            releasedate=best_candidate.releasedate,
            developer=best_candidate.developer,
            publisher=best_candidate.publisher,
            genre=best_candidate.genre,
            players=best_candidate.players,
            rating=best_candidate.rating,
        ),
        fetched_at=datetime.now(tz=timezone.utc),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_cascade.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/multiscraper/providers/cascade.py tests/unit/test_cascade.py
git commit -m "feat: add cascade logic with provider fallback and match threshold"
```

---

## Milestone Gate

- [ ] `pytest tests/unit/ -v` — all tests pass (registry, match, block_detect, cascade)
- [ ] `ruff check .` passes
- [ ] `mypy --strict src/multiscraper` passes
- [ ] Cascade correctly picks best provider, handles NO_MATCH and BLOCKED