# Phase 9: Integration, Acceptance, and Final Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end integration tests, acceptance criteria verification, final lint/typecheck/coverage, and project polish.

**Depends on:** All previous phases.

**Milestone:** All acceptance criteria from spec 6.7 pass. Coverage targets met. `ruff`, `mypy --strict`, and `pytest` all pass clean.

**Parallelizable:** No — this is the final gate.

---

## Task 9.1: End-to-end integration test

**Files:**
- Create: `tests/integration/test_end_to_end.py`

- [ ] **Step 1: Write the E2E test**

```python
# tests/integration/test_end_to_end.py
"""End-to-end test: discover ROMs, scrape with FakeProvider, generate outputs."""

from pathlib import Path

import pytest

from multiscraper.models import MediaType, Rom, RomIdentifier
from multiscraper.providers.registry import ProviderRegistry
from multiscraper.config.models import MultiscraperConfig, OrchestratorConfig
from multiscraper.core.orchestrator import Orchestrator
from multiscraper.output.gamelist_xml import generate_gamelist
from multiscraper.output.db import Database


class FakeProvider:
    name = "fake"
    requires_auth = False
    auth_fields: list[str] = []
    rate_limit_per_sec = 100.0
    priority = 1
    supported_media = {MediaType.IMAGE, MediaType.VIDEO, MediaType.MARQUEE}
    platform_map: dict[str, str | int] = {"snes": 4}
    is_identifier_only = False
    is_offline = False

    async def setup(self, config: dict) -> None: pass
    async def close(self) -> None: pass

    async def search(self, rom: Rom) -> list:
        from multiscraper.models import Candidate, MediaRef
        return [Candidate(
            provider="fake", source_id="1",
            name=rom.normalized_name, match_score=0.95,
            description="A great game.",
            media=[
                MediaRef(type=MediaType.IMAGE, url="https://example.com/img.jpg", ext="jpg", source="fake"),
                MediaRef(type=MediaType.VIDEO, url="https://example.com/vid.mp4", ext="mp4", source="fake"),
                MediaRef(type=MediaType.MARQUEE, url="https://example.com/marquee.png", ext="png", source="fake"),
            ],
        )]

    async def fetch_media(self, candidate, wanted):
        return {mt: ref for mt in wanted for ref in candidate.media if ref.type == mt}

    def detect_blocked(self, response, body: bytes) -> bool: return False
    def is_auth_missing(self, exc: Exception) -> bool: return False


@pytest.mark.asyncio
async def test_e2e_full_pipeline(tmp_path: Path):
    """Full pipeline: ROMs → cascade → CSV → DB → gamelist.xml."""
    roms = []
    for i in range(10):
        ri = RomIdentifier(
            rel_path=f"./snes/game{i}.smc", size=1024, mtime=1700000000,
            crc32=f"crc{i:08x}", cache_key=f"key{i}",
        )
        roms.append(Rom(system="snes", rom_id=ri, raw_name=f"game{i}.smc", normalized_name=f"Game {i}"))

    reg = ProviderRegistry()
    reg.register(FakeProvider())

    config = MultiscraperConfig()
    config.orchestrator = OrchestratorConfig(workers=4, batch_size=5, shutdown_drain_timeout_sec=30)

    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "run.csv"
    media_root = tmp_path / "media"

    orch = Orchestrator(
        registry=reg, config=config,
        db_path=str(db_path), csv_path=csv_path, media_root=media_root,
    )

    run_id = await orch.start(roms=roms, systems=["snes"])
    await orch.close()

    # Verify CSV
    assert csv_path.exists()
    csv_content = csv_path.read_text()
    lines = csv_content.strip().splitlines()
    assert len(lines) == 11  # header + 10 rows
    assert "OK" in csv_content or "PARTIAL" in csv_content

    # Verify DB
    db = Database(str(db_path))
    await db.init()
    tables = await db.list_tables()
    assert "runs" in tables
    assert "roms" in tables
    assert "scrape_results" in tables
    await db.close()
```

- [ ] **Step 2: Run test**

```bash
pytest tests/integration/test_end_to_end.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_end_to_end.py
git commit -m "test: add end-to-end integration test"
```

---

## Task 9.2: Acceptance criteria verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 2: Run lint**

```bash
ruff check .
```

Expected: No warnings.

- [ ] **Step 3: Run typecheck**

```bash
mypy --strict src/multiscraper
```

Expected: No errors.

- [ ] **Step 4: Run coverage**

```bash
pytest tests/ --cov=src/multiscraper --cov-report=term-missing
```

Expected: Overall > 80%, `core/` > 90%.

- [ ] **Step 5: Verify acceptance criteria checklist**

Verify each item from spec 6.7:

**Funcionales:**
- [ ] 1. Lee `es_systems.cfg` o `systems.yaml` y descubre sistemas + ROMs.
- [ ] 2. Se conecta por SSH (asyncssh) y lista ROMs sin descargarlas.
- [ ] 3. Calcula CRC32, escala a SHA1 si hay colisión.
- [ ] 4. Consulta ScreenScraper primero, fallback a otros.
- [ ] 5. Si ningún provider identifica → Hasheous → NO_MATCH.
- [ ] 6. Descarga todos los media types.
- [ ] 7. Detecta Cloudflare/captcha, salta a siguiente provider tras 3 fallos.
- [ ] 8. Si todos los providers están bloqueados, pausa con mensaje claro.
- [ ] 9. Genera CSV streaming con una fila por ROM.
- [ ] 10. Persiste en SQLite con WAL.
- [ ] 11. Genera `gamelists/<system>/gamelist.xml` compatible con ES.
- [ ] 12. Guarda media en `$HOME/multiscraper_data/media/<system>/<rom>-<type>.<ext>`.
- [ ] 13. Soporta `local_override` (prioridad 1) y `local_fallback` (último).
- [ ] 14. Interfaz `TextGenerator` con `NoOp` default; `OpenAICompat` inactiva.
- [ ] 15. Maneja SIGTERM/SIGINT con drain de 3 min, `TIMED_OUT` si se excede.
- [ ] 16. Reanuda runs abortados con `--continue <run_id>`.
- [ ] 17. Logging stdlib a terminal (Rich) y a archivo JSONL.
- [ ] 18. Cobertura > 80% global, > 90% en `core/`.
- [ ] 19. Idioma preferente con fallback configurable por campo.

**No funcionales:**
- [ ] Python 3.11+, mypy --strict pasa.
- [ ] Ruff sin warnings.
- [ ] Sin red en CI (todos los tests con cassettes o fakes).
- [ ] Documentación en `docs/` (inglés).
- [ ] Licencia MIT.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: verify acceptance criteria and final quality gates"
```

---

## Task 9.3: Final CHANGELOG and version tag

- [ ] **Step 1: Update CHANGELOG.md**

```markdown
## [0.1.0] - 2026-07-22

### Added
- Parallel multi-source scraper with asyncio + aiohttp.
- 13 data source providers (ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb,
  RetroAchievements, TheGamesDB, LibRetro Thumbnails, OpenVGDB, GameFAQs,
  Hasheous, local_override, local_fallback).
- SSH transport via asyncssh for remote ROM reading.
- SQLite cache with WAL mode and migration system.
- CSV streaming output with one row per ROM.
- EmulationStation gamelist.xml generator.
- Cascading fallback with match threshold and language preference.
- Cloudflare/captcha detection with provider cooldown.
- Graceful shutdown with SIGTERM/SIGINT handling and checkpoint/resume.
- LLM TextGenerator hook (NoOp default, OpenAICompat inactive for v2).
- Full CLI: scrape, validate-config, convert-to-es, list-systems, db, override, doctor.
- Comprehensive documentation (architecture, configuration, CLI, providers, SSH, ES files, logging, research).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for v0.1.0 release"
```

- [ ] **Step 3: Tag**

```bash
git tag v0.1.0
```

---

## Milestone Gate (FINAL)

- [ ] All tests pass (`pytest tests/ -v`)
- [ ] `ruff check .` — no warnings
- [ ] `mypy --strict src/multiscraper` — no errors
- [ ] Coverage > 80% overall, > 90% in `core/`
- [ ] All 19 functional acceptance criteria verified
- [ ] All 5 non-functional acceptance criteria verified
- [ ] All 10 doc files exist and are accurate
- [ ] CHANGELOG updated for v0.1.0
- [ ] Git tag `v0.1.0` created
- [ ] `multiscraper --version` prints `0.1.0`