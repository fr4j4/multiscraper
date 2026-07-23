# Phase 8: Documentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write all documentation files referenced in the spec. Each doc is derived from the spec sections and brainstorming decisions — no alucinations.

**Depends on:** Phase 7 (CLI, so command names are final).

**Milestone:** All 10 doc files exist, are accurate, and reference the correct spec sections.

**Parallelizable:** YES — up to 9 agents (one per doc file). README is a summary of the rest.

---

## Task 8.1: Architecture doc

**File:** `docs/architecture.md`
**Source:** Spec Sección 1 (diagrama + principios) + Sección 3 (orquestador).

- [ ] Write `docs/architecture.md` with:
  - High-level diagram (ASCII from spec)
  - Asyncio + aiohttp explanation
  - Worker/queue/supervisor model
  - Transport layer (Local + SSH)
  - Provider cascade overview
  - Output pipeline (SQLite → CSV → gamelist.xml)
- [ ] Commit: `docs: add architecture documentation`

## Task 8.2: Configuration doc

**File:** `docs/configuration.md`
**Source:** Spec Sección 4.7 (sources.yaml) + Sección 6.2 (CLI flags).

- [ ] Write `docs/configuration.md` with:
  - `sources.yaml` structure (language, output, orchestrator, providers, provider_defaults)
  - `systems.yaml` structure (roms_root, media_root, ssh_profiles)
  - Every option explained with default value
  - Env var resolution (`${env:VAR_NAME}`)
  - es_systems.cfg auto-discovery
- [ ] Commit: `docs: add configuration documentation`

## Task 8.3: CLI reference doc

**File:** `docs/cli.md`
**Source:** Spec Sección 6.2 (all commands and flags).

- [ ] Write `docs/cli.md` with:
  - `multiscraper scrape` — all flags with defaults
  - `multiscraper validate-config`
  - `multiscraper convert-to-es`
  - `multiscraper list-systems`
  - `multiscraper db {stats, vacuum, reset, show-rom, show-run, cleanup-runs}`
  - `multiscraper override {add, list, remove, import, export}`
  - `multiscraper doctor`
- [ ] Commit: `docs: add CLI reference`

## Task 8.4: Adding a provider doc

**File:** `docs/adding-a-provider.md`
**Source:** Spec Sección 4.1 (Provider Protocol) + 4.8 (registry).

- [ ] Write `docs/adding-a-provider.md` with:
  - Provider Protocol interface (all fields and methods)
  - Step-by-step: create file, implement Protocol, register in sources.yaml
  - Entry points for third-party packages
  - Example minimal provider code
  - Testing with aioresponses / vcrpy
- [ ] Commit: `docs: add provider development guide`

## Task 8.5: SSH setup doc

**File:** `docs/ssh-setup.md`
**Source:** Spec Sección 1 (SSH) + decisiones 12-15.

- [ ] Write `docs/ssh-setup.md` with:
  - Key-based auth (recommended)
  - Password auth (via env var)
  - SSH agent support
  - ProxyJump configuration
  - known_hosts strict mode (default) vs `--auto-trust`
  - asyncssh configuration
  - Example `systems.yaml` with SSH profile
- [ ] Commit: `docs: add SSH setup guide`

## Task 8.6: ES files doc

**File:** `docs/ems_files.md`
**Source:** Spec Sección 2.4 (gamelist.xml) + 2.5 (media naming).

- [ ] Write `docs/ems_files.md` with:
  - gamelist.xml structure (XML example from spec)
  - Path conventions (relative to system path)
  - releasedate format (`%Y%m%dT%H%M%S`)
  - Empty tag omission rules
  - Media naming convention (`<normalized_name>-<type>.<ext>`)
  - Media type suffix table
  - Collision handling (`_<crc32[:6]>`)
  - Media root default (`$HOME/multiscraper_data/media/`)
- [ ] Commit: `docs: add EmulationStation files documentation`

## Task 8.7: Logging doc

**File:** `docs/logging.md`
**Source:** Spec Sección 2.6 (run.log.jsonl events) + logging decisions.

- [ ] Write `docs/logging.md` with:
  - Terminal handler (Rich) + file handler (JSONL)
  - Default levels (multiscraper=INFO, libraries=WARNING)
  - Verbosity flags (`-v`, `-vv`, `-q`)
  - Full event vocabulary (all `event` values from spec 2.6)
  - JSONL line format
  - Log file location (`reports/<run_id>/run.log.jsonl`)
- [ ] Commit: `docs: add logging documentation`

## Task 8.8: Research docs

**Files:**
- `docs/research/emulationstation.md`
- `docs/research/screenscraper-api.md`
- `docs/research/alternatives.md`

**Source:** Investigación inicial (URLs en spec Apéndice B).

- [ ] Write `docs/research/emulationstation.md`:
  - How ES discovers systems (es_systems.cfg)
  - How ES scrapes (ScreenScraper.cpp, GamesDBJSONScraper.cpp)
  - gamelist.xml format (from GAMELISTS.md)
  - Media folder conventions
  - Reference URLs
- [ ] Write `docs/research/screenscraper-api.md`:
  - API v2 endpoints (jeuInfos.php, systemesListe.php)
  - Auth params (devid, devpassword, softname)
  - Media types and their SS names
  - Region/language fallback
  - Rate limits
  - Platform ID map (subset)
- [ ] Write `docs/research/alternatives.md`:
  - Comparison table of all 13 providers
  - Auth requirements, media coverage, rate limits
  - Status as of 2026
- [ ] Commit: `docs: add research documentation (ES, ScreenScraper, alternatives)`

## Task 8.9: README

**File:** `README.md`
**Source:** Summary of all docs.

- [ ] Write `README.md` with:
  - Project description (1 paragraph)
  - Quickstart (install, configure, run)
  - Features list
  - SSH example
  - Provider list
  - Links to all docs
  - License (MIT)
- [ ] Commit: `docs: update README with quickstart and feature list`

---

## Milestone Gate

- [ ] All 10 doc files exist
- [ ] Each doc references the correct spec section
- [ ] No "TBD" or "TODO" in any doc
- [ ] README has working quickstart