# AGENTS.md

Notes for AI coding agents working in this repo. Keep changes small, mirror
existing style, and verify with the commands below before claiming done.

## Stack and layout

- Python 3.11+, asyncio + aiohttp. Source layout: `src/multiscraper/`.
- CLI entry point: `multiscraper.cli:main` (also runnable as
  `python -m multiscraper`).
- Tests: `tests/unit/` and `tests/integration/`. `pytest-asyncio` is in
  `auto` mode — no `@pytest.mark.asyncio` decorator needed; just write
  `async def test_...`.
- Build backend: hatchling. Package data includes
  `src/multiscraper/db/migrations/*.sql` (SQL is applied at
  `Database.init` time, not via Alembic — just add a new `NNNN_*.sql`
  file to that directory).
  Current migrations: `0001_initial.sql`, `0002_discovered_roms.sql`
  (the latter adds a per-run temporary table for pipelining discovery
  into workers).
- Tooling: `ruff` (lint, line-length 100, target py311) and `mypy
  --strict` (tqdm is the only allowlisted missing-imports entry).

## Dev commands

```bash
pip install -e ".[dev]"          # install package + dev deps
pytest                           # full suite, no network needed
pytest tests/unit/test_X.py      # single file
pytest -k "name_substring"       # single test or subset
mypy src                         # strict type-check
ruff check src                   # lint
```

No pre-commit config and no CI workflow is committed yet. Run the
three checks above locally before finishing.

## Config files (three, all required)

The CLI assumes `config/{config,sources,systems}.yaml` exist; the
`.example` siblings are templates. They are gitignored on purpose, so
copy them in and edit. `validate-config` reads all three.

| File | Purpose |
|---|---|
| `config/config.yaml` | Transports (`local`/`ssh`), `current_transport`, defaults, `orchestrator` tunables (workers, batch_size, …). |
| `config/sources.yaml` | Provider cascade (priority order, enabled flags, per-provider `config:`), `provider_defaults`, `language`, `output`. |
| `config/systems.yaml` | List of emulated systems. Each has `name`, exactly one of `relative_path` or `full_path`, and `extensions` (no leading dot required). |

YAML supports `${env:VAR}` substitution (`config/loader.py`); missing
vars resolve to empty string. `.env` is loaded by `python-dotenv` in
the CLI entry point — credentials in `config/*.yaml` will be picked
up from `.env` automatically.

Note: `orchestrator:` is in `config.yaml`, not `sources.yaml`. This
is easy to misremember; the `--workers` / `--batch-size` CLI flags
mirror it but most `provider_defaults` (timeout, rate_limit, …) only
have YAML as their source of truth — the CLI only overrides
`match_threshold`.

## Code map

- `cli.py` — Click group. Subcommands: `scrape`, `validate-config`,
  `convert-to-es`, `list-systems`, `db {stats,vacuum}`,
  `override {add,list}`, `doctor`. The `scrape` command is the only
  one that actually runs a full pipeline today; others are
  scaffolds/stubs (see `convert-to-es`, `db stats`, `override add`).
- `scrape.py` — end-to-end skeleton: launches discovery as an
  asyncio task, runs one orchestrator per system, truncates the
  temporary `discovered_roms` table at the start and end of the run.
- `core/orchestrator.py` — workers claim rows from `discovered_roms`
  in the DB (no in-memory queue anymore), run the cascade, write CSV
  rows, mark rows `completed`. Owns aiohttp session and signal
  handlers. Constructor takes a pre-built `db: Database` and
  `run_id: str`; no longer owns the DB lifecycle.
- `core/discovery.py` — parallel `discover_system` (gather + semaphore)
  that lists a system, bulk-inserts `pending` rows, then hashes them
  and updates each row to `done`/`failed`. Skip-before-hash:
  for each file it consults the `roms` cache and reuses the
  `cache_key` if size + mtime + last_scrape_at are consistent, which
  avoids re-hashing unchanged files on warm caches. With
  `--force-rescrape` the hash is always recomputed. See
  `docs/discovery.md`.
- `providers/registry.py` — central registry. `register_all()` is a
  hard-coded import list — add a new provider by importing it there
  and appending the class. `register_class` registers, `setup_from_config`
  instantiates and wires auth from `sources.yaml`.
- `providers/base.py` — `Provider` and `Identifier` Protocols
  (runtime_checkable). Every provider file implements these; see
  `docs/adding-a-provider.md`.
- `providers/cascade.py` — `run_cascade`: cache check → media
  cascade (priority order, threshold) → identifier cascade
  (Hasheous) → media download in parallel bounded by
  `media_concurrency`.
- `providers/{block_detect,match,normalize,retry}.py` — shared
  helpers.
- `transport/{local,ssh}.py` — ROM I/O without downloading bytes;
  runs `crc32`/`sha1sum` server-side for SSH.
- `output/{db,csv_writer,gamelist_xml,log_jsonl,summary}.py` —
  SQLite WAL, streaming CSV, ES XML, JSONL events, run summary.
- `config/{loader,models,es_systems_parser}.py` — YAML + env
  resolution, Pydantic models, optional `es_systems.cfg` ingestion.
- `doctor.py` — diagnostic checks for SSH, credentials, disk, etc.

## Provider authoring checklist

When adding or modifying a provider:

1. Implement the `Provider` Protocol in `src/multiscraper/providers/`.
   Field `name` is the registry key and must match the `id:` in
   `sources.yaml`. Use `ClassVar[...]` annotations.
2. Append the class to the import list in
   `providers/registry.py::register_all`.
3. Add tests under `tests/unit/test_provider_<name>.py`. Use
   `aioresponses` for HTTP mocking (42 existing usages — do not
   introduce a second pattern). `conftest.py` already patches
   `aioresponses` for aiohttp ≥3.11.
4. Reference docs: `docs/adding-a-provider.md`,
   `docs/data_providers.md`.

## Tests: what to know

- No network required by default. `aioresponses` mocks all HTTP.
  `vcrpy` is declared in dev deps but is **not** actually used in
  the tree — README mentions cassettes, that is stale; ignore.
- Markers: `network` and `slow` are declared in `pyproject.toml` but
  no test currently uses them; `-m "not network"` is a no-op today.
- `tests/conftest.py` provides a per-test `event_loop` fixture and
  monkey-patches `aioresponses` for newer aiohttp. Do not remove.
- `tests/integration/test_end_to_end.py` is the smoke test: builds
  an orchestrator with a `FakeProvider` and asserts the full
  pipeline writes results.

## Output artifacts and state locations

- SQLite cache: `cache.db` in CWD by default (CLI writes it there).
  Override via `config.yaml::defaults.cache_db`. WAL mode, schema in
  `db/migrations/0001_initial.sql`.
- CSV reports: `reports/<run_id>/run.csv` (or wherever `--csv`
  points).
- Media: `media/<system>/<rom>-<type>.<ext>` by default; override
  via `--media-root`.
- Gameloogs: `gamelists/<system>/gamelist.xml` (written by the
  `convert-to-es` path).
- All of the above are gitignored. `scripts/clean.sh [--force |
  --dry-run]` wipes cache, reports, media, and `run.log.jsonl` — use
  it before manual smoke tests; it does **not** touch `.env` or
  `config/*.yaml`.

## Style and conventions

- `.editorconfig`: UTF-8, LF, final newline, trim trailing
  whitespace; Python 4-space, YAML 2-space, Markdown leaves trailing
  whitespace alone.
- Do not add comments unless the user asks.
- Type annotations everywhere. `mypy --strict` is part of the dev
  loop; new code without full annotations will fail CI later.
- Async I/O: never block. Local file hashing routes to a thread
  pool via `loop.run_in_executor` (`LocalTransport._hash_sync`);
  follow the same pattern for any new blocking work.
- Logging: log through `multiscraper.*` loggers; do not add
  handlers — `logging_setup.setup_logging` owns them. Library
  loggers (`aiohttp`, `asyncio`, `asyncssh`, …) are silenced to
  WARNING by default; `-vv` raises them.
- `MediaType` and `ScrapeStatus` are `StrEnum`s in `models.py`.
  New statuses are a deliberate API change.

## Common pitfalls

- `--config` defaults to `config/sources.yaml`; `--config-dir`
  (containing `config.yaml` + `systems.yaml`) defaults to `config/`.
  The two are separate; both must be correct.
- `System` model requires exactly one of `relative_path` /
  `full_path`, not both, not neither (`config/models.py` enforces).
- Transport `name` and `current_transport` must match exactly;
  names are validated by regex `^[a-z0-9_]{1,32}$`.
- `LocalProvider` is registered with `name = "local"` but is
  configured in `sources.yaml` as `id: local_override` and
  `id: local_fallback` — those are two roles, one class, two
  priority slots.
- The `Orchestrator` installs a signal handler on the current
  event loop. Re-entering `asyncio.run` in tests can collide; pass
  a pre-built `transport` to `run_scrape_skeleton` to skip the
  default SSH/Local setup.
- `config/sources.yaml` in this repo has most providers commented
  out and `local_fallback` enabled. Don't assume the example file
  matches what's checked in.

## Where to look first when something breaks

- Config error? Run `multiscraper validate-config`.
- Provider cascade order or threshold? `config/sources.yaml` →
  `provider_defaults`, `--match-threshold`. Cascade logic is in
  `providers/cascade.py`.
- Workers hanging? Check `Orchestrator._worker_loop` and the
  `Supervisor` (60s window, 3 failures = quarantine). DLQ is in
  `Supervisor.dlq`.
- SIGTERM behavior: `core/shutdown.py`. First signal = soft drain;
  second = force cancel; jobs in flight after `--shutdown-timeout`
  (default 180s) become `TIMED_OUT`.
- SSH issues? `docs/ssh-setup.md`. Use `--auto-trust` only on LANs.
- Re-scraping / cache control: `--skip-existing` is on by default;
  `--force-rescrape` redoes everything, `--no-cache` skips the
  cache lookup but still writes to it. **Discovery** has its own
  cache: a rom already in the `roms` table with matching size +
  mtime + a recent `last_scrape_at` is not re-hashed; it goes
  straight to the worker as SKIPPED. Use `--force-rescrape` to
  bypass this.
