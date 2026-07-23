# multiscraper — Architecture

`multiscraper` is an asyncio + aiohttp parallel scraper for retro gaming
frontends. It discovers ROMs from a local folder or a remote SSH host,
queries multiple metadata providers in a cascading fallback chain,
downloads media, and writes EmulationStation-compatible `gamelist.xml`
plus a per-run CSV and a JSONL log.

This document covers the high-level architecture: the run-time
components, the queue/worker/supervisor model, the provider cascade,
the transport layer, and the output pipeline. It is the map; the
individual subsystems (configuration, providers, SSH, ES files,
logging) have their own dedicated documents.

## Components

| Layer | Module | Responsibility |
|---|---|---|
| CLI | `src/multiscraper/cli.py` | Click commands (`scrape`, `validate-config`, `convert-to-es`, `list-systems`, `db`, `override`, `doctor`). |
| Orchestrator | `src/multiscraper/core/orchestrator.py` | Owns the run: builds jobs, spawns workers, drives the queue, supervises failures, persists results. |
| Workers | `src/multiscraper/core/orchestrator.py` (`_worker_loop`) | One `asyncio.Task` per worker. Pulls a `Job`, runs the cascade, downloads media, writes one row. |
| Queue | `asyncio.Queue[Job]` | Single FIFO queue populated by the orchestrator and drained by the workers. |
| Supervisor | `src/multiscraper/core/supervisor.py` | Decides requeue vs. DLQ when a worker fails. |
| Shutdown | `src/multiscraper/core/shutdown.py` | Installs SIGTERM/SIGINT handlers, sets a soft-drain event. |
| Transport | `src/multiscraper/transport/{local,ssh,base}.py` | Lists, stats, and hashes ROMs without downloading them. |
| Providers | `src/multiscraper/providers/*.py` | One module per source. `Provider` Protocol plus the `Identifier` sub-Protocol. |
| Output | `src/multiscraper/output/{db,csv_writer,gamelist_xml,log_jsonl,summary}.py` | SQLite WAL cache, streaming CSV, ES XML, JSONL events, summary. |
| Config | `src/multiscraper/config/{loader,models,es_systems_parser}.py` | YAML + `es_systems.cfg` parsing, validation, `${env:...}` resolution. |
| Logging | `src/multiscraper/logging_setup.py` | Rich terminal handler + JSONL file handler. |

## High-level diagram

```
+------------------------------------------------------------------+
|                          CLI (click)                             |
|  --roms-root | --es-systems | --config | --workers N             |
|  --batch-size | --priority-config | --force-rescrape            |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                  Orchestrator (asyncio)                          |
|  - Carga config (es_systems.cfg + YAML override)                |
|  - Crea RunContext (run_id, csv_path, logs)                     |
|  - Construye cola de Jobs: 1 Job = 1 ROM + sistema + lote       |
|  - Spawnea N workers (asyncio tasks)                            |
|  - Supervisa workers, recupera tareas muertas                   |
|  - Empuja resultados al CSV writer en streaming                  |
+----+-------------------+-------------------+---------------------+
     |                   |                   |
     v                   v                   v
+------------+   +------------------+   +-----------------+
| Config &   |   | Job Queue        |   | CSV Writer      |
| Cache layer|   | (asyncio.Queue)  |   | (stream, lock)  |
| - sources  |   | partition by sys |   |                 |
| - cache.db |   | batches de B     |   |                 |
| - gamelist|   +------------------+   +-----------------+
+------------+
                              |
                              v
+------------------------------------------------------------------+
|              Worker (asyncio task) -- N in parallel              |
|  1. Toma Job de la cola                                         |
|  2. Chequea cache (SQLite) -- si hit, salta                      |
|  3. Itera providers en orden de prioridad                        |
|     a. search(rom) -> candidates                                 |
|     b. select_best(candidates, language) -> chosen               |
|     c. fetch_media(chosen, wanted_types)                         |
|  4. Empaqueta Result                                              |
|  5. Devuelve a Orchestrator                                       |
+----------------------------------+-------------------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|              Source Providers (plugins tipados)                  |
|  ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb,               |
|  RetroAchievements, TheGamesDB, LibRetro Thumbnails,            |
|  OpenVGDB, GameFAQs, Hasheous, local_override, local_fallback   |
|  Cada uno implementa Provider Protocol:                          |
|    name, requires_auth, async search, async fetch_media,        |
|    platform_map, detect_blocked(response)                        |
+----------------------------------+-------------------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|             Output stage                                         |
|  - .cache/multiscraper.db (SQLite con WAL)                       |
|  - $HOME/multiscraper_data/media/<system>/<rom>-<type>.<ext>    |
|  - gamelists/<system>/gamelist.xml  (conversor)                 |
|  - reports/<run_id>/run.csv                                     |
|  - reports/<run_id>/run.log.jsonl                               |
|  - reports/<run_id>/summary.json                                |
+------------------------------------------------------------------+
```

The diagram is ASCII for portability in terminals and code review.
The corresponding ASCII sources are in
`docs/superpowers/specs/2026-07-22-multiscraper-design.md` (Sección 1).

## Asyncio + aiohttp model

The whole run lives in a single `asyncio` event loop. There are three
kinds of coroutines:

- **Workers** — N of them (default 8, `orchestrator.workers` in
  `sources.yaml`). Each pulls one `Job` from the queue, runs the
  cascade, and writes one row to the CSV writer.
- **CSV writer loop** — Coroutine that drains the result queue and
  flushes every 50 rows.
- **Shutdown handler** — Installs `SIGTERM`/`SIGINT` via
  `loop.add_signal_handler` in `ShutdownHandler.install`. The first
  signal sets a soft-drain event; the second forces cancellation.

I/O is `aiohttp` for HTTP and `asyncssh` for SSH. Blocking syscalls
(e.g. CRC32 of a large local file) are routed to a thread pool via
`loop.run_in_executor` in `LocalTransport._hash_sync`.

## Queue, workers, supervisor

### Job queue

A single `asyncio.Queue[Job]` holds all jobs. The orchestrator
pre-loads it from `batch_jobs()` in `core/batcher.py` before workers
start. There is no per-system queue; workers are cross-batch.

A `Job` is defined in `core/job.py` and carries the `Rom`, the
`run_id`, the `batch_id`, and a monotonically increasing `attempts`
counter.

### Worker loop

`Orchestrator._worker_loop` is the canonical worker:

```python
while not self._shutdown.is_set:
    try:
        job = await asyncio.wait_for(self._queue.get(), timeout=2.0)
    except TimeoutError:
        if self._queue.empty() and not self._shutdown.is_set:
            return
        continue
    try:
        result = await self._process_job(job)
        await self._csv_writer.write_row(...)
    except Exception as exc:
        if self._supervisor is not None:
            await self._supervisor.report_failure(worker_id, job, exc)
    finally:
        self._queue.task_done()
```

The 2-second timeout lets workers notice a quiet queue without
starving on `queue.get()`.

### Supervisor

`Supervisor` (`core/supervisor.py`) tracks failures per worker in a
sliding window. The policy from spec decisión #11:

- 1 isolated failure -> requeue with exponential backoff (2s, 4s, 8s).
- 3 failures of the same worker in 60s -> worker is quarantined; the
  current job is parked in `self.dlq`.
- 3 retries of the same job -> DLQ.

A real example of failure handling: a network blip while fetching
`http://api.screenscraper.fr/...` raises `NetworkError`; the worker
catches it, calls `supervisor.report_failure`, and the job is
re-queued with a backoff. Three such blips in 60 seconds and that
worker is quarantined; the next one to fail goes to the DLQ.

## Provider cascade

The cascade has two independent sub-cascades: one for **identification**
and one for **media**. Both are implemented in
`providers/cascade.py` (`run_cascade`).

1. **Cache check.** If the ROM has a `scrape_results` row, the
   worker short-circuits with `ScrapeStatus.SKIPPED`.
2. **Media cascade.** For each provider in priority order, run
   `provider.search(rom)`. If the top candidate's `match_score` is
   above `provider_defaults.match_threshold` (default `0.7`), stop.
3. **Identifier cascade.** If no provider matched, run
   `Identifier.identify(rom)` (Hasheous by default) to get a
   canonical name, then re-run the media cascade with that name.
4. **Choose best.** Sort candidates by `match_score` and language
   preference (`pick_best_with_language` in `cascade.py`).
5. **Media fetch.** For each wanted `MediaType`, iterate providers
   in priority order until one returns a URL. Skip blocked providers.
6. **Download in parallel.** All chosen media files are fetched with
   `asyncio.gather` bounded by `media_concurrency` (default 4).
7. **Persist.** `ScrapedResult` is written to the `scrape_results`
   table, each `MediaFile` to `media`, and per-field language
   provenance to `text_provenance`.

If the cascade never reaches `match_threshold`, the run emits a
`ScrapedResult` with `status=NO_MATCH`. ES then renders only a bare
`<path>` for the ROM.

### Blocked-provider tracking

The cascade consults a `blocked_providers: set[str]` before calling
any provider. The orchestrator populates it on:

- `BlockedError` or `RateLimitError` from a provider
- 3 consecutive failures within `worker_failure_window_sec` (60s
  default).

Blocked providers stay out of the cascade for
`cooldown_after_blocked_sec` (30 min default).

## Transport layer

The transport is the I/O boundary between the orchestrator and the
file system. The Protocol lives in
`src/multiscraper/transport/base.py`:

```python
class RomTransport(Protocol):
    async def list_dir(self, path: str) -> list[str]: ...
    async def file_info(self, path: str) -> FileInfo: ...
    async def hash(self, path: str, algo: Literal["crc32","sha1"]) -> str: ...
    async def open_read(self, path: str, max_bytes: int | None = None) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...
```

There are two concrete implementations:

- `LocalTransport` (`transport/local.py`) for paths on the local
  filesystem. `hash()` dispatches CRC32 / SHA1 to a thread pool.
- `SshTransport` (`transport/ssh.py`) for remote hosts. Uses
  `asyncssh.connect`, runs `crc32` or `sha1sum` over `conn.run`, and
  streams ROMs via `conn.create_process("cat path")`.

The transport never downloads the ROM itself. It returns metadata
(`FileInfo`) and a hash so the orchestrator can build a
`RomIdentifier` and look up the cache. The actual ROM bytes are only
read when computing the hash.

See `docs/ssh-setup.md` for the SSH-specific knobs (keys, agents,
ProxyJump, known_hosts strictness).

## Output pipeline

The output stage (`src/multiscraper/output/`) writes five artefacts
per run:

1. **SQLite cache** (`.cache/multiscraper.db`, WAL mode). Tables:
   `runs`, `roms`, `scrape_results`, `media`, `run_jobs`,
   `provider_state`, `source_overrides`, `text_provenance`. See
   spec Sección 2.2 for the full schema.
2. **CSV** (`reports/<run_id>/run.csv`). One row per ROM, columns
   per `MediaType`. Streamed through `CsvWriter` (`output/csv_writer.py`)
   with a 50-row flush. See spec Sección 2.3.
3. **gamelist.xml** (`gamelists/<system>/gamelist.xml`). Generated
   by `output/gamelist_xml.py` from cached `ScrapedResult` objects.
   See `docs/ems_files.md` for the format.
4. **JSONL event log** (`reports/<run_id>/run.log.jsonl`). One event
   per line. Written by `JsonlLogWriter` (`output/log_jsonl.py`).
5. **Summary** (`reports/<run_id>/summary.json`). Aggregate totals
   per system plus warnings and error samples. Written by
   `output/summary.py`.

The CSV and the SQLite cache are populated incrementally as workers
finish. The XML, summary, and final JSONL are written when the run
ends (or on resume).

## Run lifecycle

A normal run goes through these phases:

1. **Bootstrap.** `multiscraper scrape` parses flags, calls
   `setup_logging`, loads the config, and (for the actual run path)
   hands off to the orchestrator.
2. **Job planning.** The transport lists ROMs per system. The
   orchestrator constructs `Rom` objects with normalized names and
   `RomIdentifier`s, creates a `runs` row with a fresh `ULID`, and
   batches them via `batch_jobs`.
3. **Execution.** Workers drain the queue. The supervisor and the
   blocked-provider tracker respond to errors.
4. **Drain or abort.** On `SIGTERM`, the soft-drain event is set;
   workers finish their current job and stop pulling. On hard
   timeout (`--shutdown-timeout`, default 180s) the job is canceled
   with `status=TIMED_OUT`. The run is marked `aborted` and the user
   can resume with `--continue <run_id>`.
5. **Finalize.** The CSV is flushed, the DB is closed, and the
   orchestrator prints a summary. `convert-to-es` produces
   `gamelist.xml` files from the cached `ScrapedResult` set.

## Where to go next

- `docs/configuration.md` — full YAML reference.
- `docs/cli.md` — every CLI flag with its default.
- `docs/adding-a-provider.md` — how to write a new `Provider`.
- `docs/ssh-setup.md` — SSH configuration and security modes.
- `docs/ems_files.md` — `gamelist.xml` and media file format.
- `docs/logging.md` — terminal and JSONL logging.
- `docs/research/{emulationstation,screenscraper-api,alternatives}.md`
  — research notes on upstream systems and providers.
