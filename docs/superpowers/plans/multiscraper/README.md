# multiscraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `multiscraper`, a parallel multi-source scraper for retro gaming frontends (EmulationStation-compatible), with SSH transport, 13 data sources in cascading fallback, SQLite cache, CSV logging, and an LLM hook (inactive in v1).

**Architecture:** Asyncio + aiohttp orchestration with N workers consuming a shared job queue. Providers implement a `Provider` Protocol and are registered via entry points. Output is a JSON cache (SQLite) + converter to EmulationStation `gamelist.xml`. SSH access via `asyncssh` to read ROMs from a remote arcade without downloading them.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, asyncssh, pydantic v2, aiosqlite, click, rich, lxml, PyYAML, vcrpy (tests), pytest, ruff, mypy --strict.

## Global Constraints

- Python >= 3.11 (uses `asyncio.TaskGroup`, `tomllib`, `ExceptionGroup`).
- Type hints strict; `mypy --strict` must pass in CI.
- `ruff` with rules E/F/W/I/UP/B/SIM/RUF, line-length 100, target py311.
- No code comments except docstrings (Google format for public functions).
- No file > 400 lines; split if it grows.
- TDD: write failing test first, then minimal implementation.
- Frequent commits: one commit per task step.
- No network in CI: all tests use vcrpy cassettes or fakes.
- License: MIT.
- Docs in English.
- Logging: stdlib `logging` + rich handler to terminal + JSONL to file. Libraries silenced to WARNING by default; `-vv` raises them to INFO.
- Media root default: `$HOME/multiscraper_data/media/` (not hidden, configurable).
- Hash: crc32 by default with automatic fallback to sha1 on collision.
- Cache: SQLite with WAL mode, in `.cache/multiscraper.db`.
- Shutdown: `--shutdown-timeout 180` (3 min soft drain); `TIMED_OUT` status if exceeded.
- Provider cooldown after block: 30 min default (configurable).
- `match_threshold` default: 0.7 (configurable).
- Language: `text_priority` and `name_priority` with `best_effort` fallback strategy by default.

## Reference

- **Spec:** `docs/superpowers/specs/2026-07-22-multiscraper-design.md`
- **Phases:** one file per phase in this directory (`phase-0-*.md` through `phase-9-*.md`).

## Phase Overview (with milestones)

| Phase | File | Goal | Milestone (testable) | Parallelizable? |
|---|---|---|---|---|
| 0 | `phase-0-scaffold.md` | Project skeleton, pyproject, CLI stub, logging | `multiscraper --version` works; `pytest` collects 0 tests | No (foundation) |
| 1 | `phase-1-models-utils.md` | Pydantic models + utils (hash, http, fs, retry) | Unit tests pass for models, hash, retry | Yes (4 independent tracks) |
| 2 | `phase-2-config-transport.md` | Config loader + transport (local + SSH) | `validate-config` command works; SSH transport lists remote dir | Yes (2 independent tracks) |
| 3 | `phase-3-output-layer.md` | SQLite schema + migrations + CSV writer + gamelist XML + summary + log JSONL | DB roundtrip test; CSV write test; XML gen test | Yes (3 independent tracks) |
| 4 | `phase-4-providers-core.md` | Provider Protocol, Identifier Protocol, registry, normalize, match, cascade, block_detect | Cascade logic unit tests with FakeProvider | Partially (core first, then providers) |
| 5 | `phase-5-providers-impl.md` | Implement 13 providers with cassettes | Each provider has passing tests with cassette | Yes (up to 11 agents) |
| 6 | `phase-6-orchestrator.md` | Orchestrator, queue, batcher, worker, supervisor, checkpoint, shutdown | End-to-end test with FakeProvider + FakeTransport | No (integration) |
| 7 | `phase-7-cli-llm.md` | Full CLI (all commands + flags) + LLM hook (NoOp + OpenAICompat inactive) | `multiscraper scrape --dry-run` works; `doctor` works | Yes (2 tracks) |
| 8 | `phase-8-docs-polish.md` | Documentation (README, architecture, config, cli, adding-a-provider, ssh-setup, ems_files, logging, research) | All docs exist and are accurate | Yes (9 independent docs) |
| 9 | `phase-9-integration-acceptance.md` | E2E integration tests, acceptance criteria verification, final lint/typecheck | All acceptance criteria pass; coverage targets met | No (final gate) |

## Multi-Agent Execution Strategy

```
Phase 0 (sequential) ──► Phase 1 (4 agents) ──► Phase 2 (2 agents) ──► Phase 3 (3 agents)
                                                                      │
                                                                      ▼
                                                              Phase 4 (sequential core)
                                                                      │
                                                                      ▼
                                                              Phase 5 (11 agents, one per provider)
                                                                      │
                                                                      ▼
                                                              Phase 6 (sequential integration)
                                                                      │
                                                                      ▼
                                                              Phase 7 (2 agents)
                                                                      │
                                                                      ▼
                                                              Phase 8 (9 agents, docs)
                                                                      │
                                                                      ▼
                                                              Phase 9 (final gate)
```

**Rules for multi-agent dispatch:**
- Each task within a phase is independent unless explicitly marked `Depends on: Task X`.
- A phase's milestone gate must pass before the next phase starts.
- Each agent gets one task file (self-contained with code, tests, commands).
- Agents commit after each step; the orchestrator reviews between tasks.
- Cassettes for provider tests are recorded by a dedicated agent with `--record-mode=once` (manual, not in CI).

## How to read this plan

1. Start with `phase-0-scaffold.md` (sequential, no parallelism).
2. After Phase 0 milestone passes, dispatch Phase 1 tasks to up to 4 agents.
3. Continue per the dependency graph above.
4. Each phase file is self-contained: it has its own header, tasks, code, tests, and commit steps.
5. The milestone at the end of each phase is the gate: if it fails, do not proceed.