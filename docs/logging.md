# Logging

`multiscraper` uses the standard `logging` module with two
handlers:

- A `rich.logging.RichHandler` for the terminal.
- A `logging.FileHandler` with a `JsonlFormatter` for the
  structured per-run log.

The configuration is in
`src/multiscraper/logging_setup.py`. The CLI calls
`setup_logging(...)` once per command; everything else uses
`logger = logging.getLogger(__name__)` as usual.

## Handler reference

### Terminal handler (Rich)

`RichHandler` (`rich_tracebacks=True, show_path=False`). The
`multiscraper` logger is the one and only logger that emits to the
terminal by default. Its level is set from the verbosity flags
(see below). Rich handles the colors, the tracebacks, and the
timestamps.

### File handler (JSONL)

A `logging.FileHandler` is attached when `--log-file PATH` is
given. The path is created with `parents=True, exist_ok=True`. The
formatter is `JsonlFormatter` from the same module.

A `JsonlFormatter` line looks like:

```json
{"ts":"2026-07-22T22:00:01.450Z","level":"DEBUG","logger":"multiscraper.core.worker","message":"hash_upgraded rom=./snes/Suspect.crc from=crc32 to=sha1 reason=collision"}
```

Schema:

| Key | Source |
|---|---|
| `ts` | `datetime.fromtimestamp(record.created, tz=UTC).isoformat()` |
| `level` | `record.levelname` |
| `logger` | `record.name` |
| `message` | `record.getMessage()` |
| `exc_info` | `record.exc_info` if present (formatted by `formatException`) |

The `**extra` fields passed to the logger (e.g. `extra={"rom":
"./snes/Foo.smc", "provider": "screenscraper"}`) are not flattened
into the JSON by `JsonlFormatter`; if you need them in the JSONL
output, use the dedicated `JsonlLogWriter` from
`src/multiscraper/output/log_jsonl.py` instead, which writes the
event vocabulary listed below.

## Default levels

| Logger | Default level |
|---|---|
| `multiscraper` | `INFO` |
| `multiscraper.*` | inherits from `multiscraper` |
| `aiohttp`, `asyncio`, `asyncssh`, `httpx`, `urllib3`, `vcr` | `WARNING` |

Spec decisión #23: libraries are silenced by default so a long
run does not flood the terminal with HTTP traces.

## Verbosity flags

The CLI flags `-v`, `-vv`, and `-q` are surfaced on every
subcommand. The mapping is in `setup_logging`:

| Flag | `multiscraper.*` level | Library level |
|---|---|---|
| (default) | `INFO` | `WARNING` |
| `-v` | `DEBUG` | `WARNING` |
| `-vv` | `DEBUG` | `INFO` |
| `-q` | `WARNING` | `WARNING` |

```python
def setup_logging(*, verbose: int = 0, quiet: bool = False, log_file: Path | None = None) -> None:
    if quiet:
        ms_level = logging.WARNING
    elif verbose >= 1:
        ms_level = logging.DEBUG
    else:
        ms_level = logging.INFO

    lib_level = logging.INFO if verbose >= 2 else logging.WARNING
```

`-vv` is what you want for diagnosing a flaky provider. Use
`--log-file` alongside it so the JSONL captures the same
messages.

## Event vocabulary (spec Sección 2.6)

A second, structured log is written by `JsonlLogWriter` to
`reports/<run_id>/run.log.jsonl`. This is the canonical event
stream for tools and dashboards. The `event` field is a closed
vocabulary; new events need a spec change.

| Event | Trigger |
|---|---|
| `run_start` | Orchestrator starts. `run_id`, `systems`. |
| `run_end` | Orchestrator exits. `status`, `totals`. |
| `run_paused` | All providers blocked. |
| `run_resumed` | `--continue <run_id>` picks up an aborted run. |
| `run_aborted` | Hard timeout or double SIGINT. |
| `rom_discovered` | Transport returns a new ROM. |
| `rom_started` | Worker picks up a job. |
| `rom_done` | Worker emits a `ScrapedResult`. `status`, `provider`, `elapsed_ms`. |
| `rom_failed` | Worker caught an exception. `error`. |
| `rom_skipped` | Cache hit, status `SKIPPED`. |
| `provider_called` | Provider's `search` was invoked. `provider`, `rom`. |
| `provider_blocked` | Detector tripped, provider marked blocked. `provider`, `reason`, `blocked_until`. |
| `provider_skipped` | Provider skipped because blocked. |
| `provider_unblocked` | Cooldown elapsed, provider re-enabled. |
| `hash_upgraded` | Auto-upgrade from CRC32 to SHA1 on collision. |
| `hash_failed` | Hashing raised an exception. |
| `cache_hit` | Cached result reused. |
| `cache_miss` | No cached result, cascade ran. |
| `cache_invalidated` | `--force-rescrape` discarded a cached result. |
| `media_downloaded` | A media file finished. `type`, `bytes`. |
| `media_failed` | A media download failed. `type`, `error`. |
| `media_skipped` | A media type was disabled. |
| `ssh_connected` | `SshTransport` opened a connection. |
| `ssh_disconnected` | `SshTransport` closed. |
| `ssh_reconnected` | Connection dropped and re-opened. |
| `ssh_error` | SSH operation raised. |
| `worker_started` | Worker task launched. |
| `worker_died` | Worker task raised. `worker`, `error`. |
| `worker_recovered` | Supervisor re-queued the job. |
| `shutdown_initiated` | First SIGTERM/SIGINT. |
| `worker_drained` | Worker finished its job and is exiting. |
| `worker_force_cancelled` | Job exceeded shutdown timeout, cancelled. |
| `all_providers_blocked` | Cascade cannot proceed; run paused. |

### JSONL line format (event log)

```json
{"ts":"2026-07-22T22:00:01.450Z","level":"DEBUG","event":"hash_upgraded","rom":"./snes/Suspect.crc","from":"crc32","to":"sha1","reason":"collision"}
{"ts":"2026-07-22T22:00:03.220Z","level":"INFO","event":"rom_done","rom":"./snes/Super Mario World (USA).smc","status":"OK","provider":"screenscraper","elapsed_ms":1234}
```

Schema:

| Key | Source |
|---|---|
| `ts` | `datetime.now(tz=UTC).isoformat()` |
| `level` | `level` arg to `log_event` (default `INFO`) |
| `event` | Event name from the vocabulary |
| additional keys | The `**kwargs` passed to `log_event` |

## Log file locations

- Terminal: stdout, no file.
- `--log-file PATH`: append-only JSONL of the standard log records
  (`multiscraper` logger only).
- `reports/<run_id>/run.log.jsonl`: the structured event log. This
  is what tools consume.

The default `reports/` directory is created by the orchestrator
under the current working directory unless `--csv` or a different
`--out` is given.

## Examples

Terminal-only INFO run:

```bash
multiscraper scrape --systems snes
```

DEBUG for `multiscraper`, INFO for libraries, with a JSONL
trail:

```bash
multiscraper scrape -vv --log-file /tmp/multiscraper.jsonl --systems snes
```

Quiet mode (warnings and errors only):

```bash
multiscraper scrape -q --systems snes
```

Tail the JSONL event log while a run is in progress:

```bash
tail -f reports/01HXYZ.../run.log.jsonl | jq .
```
