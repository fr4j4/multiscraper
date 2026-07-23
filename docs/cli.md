# CLI Reference

`multiscraper` ships a single Click entry point declared in
`pyproject.toml` as `multiscraper = "multiscraper.cli:main"`. The
group and all subcommands live in `src/multiscraper/cli.py`.

```bash
multiscraper --version
multiscraper --help
multiscraper <command> --help
```

## Commands at a glance

| Command | Purpose |
|---|---|
| `scrape` | Run a full scrape pass against the configured systems. |
| `validate-config` | Load and validate `sources.yaml` (and optionally `es_systems.cfg`). |
| `convert-to-es` | Convert a previously cached run into `gamelist.xml` files. |
| `list-systems` | List the systems discovered from `es_systems.cfg` and/or `roms_root`. |
| `db` | Database subcommands: `stats`, `vacuum`, `reset`, `show-rom`, `show-run`, `cleanup-runs`. |
| `override` | Manage `source_overrides` rows: `add`, `list`, `remove`, `import`, `export`. |
| `doctor` | Diagnostic sweep: SSH reachability, provider credentials, disk space. |

## `multiscraper scrape`

The workhorse. Runs the orchestrator against the configured systems.

```
multiscraper scrape [OPTIONS]
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--roms-root` | path | `None` | Root directory for ROMs. Local path or `ssh://...` URL. |
| `--media-root` | path | `None` | Output directory for downloaded media. Falls back to `systems.yaml::media_root`, then `$HOME/multiscraper_data/media/`. |
| `--es-systems` | path | `None` | Explicit path to `es_systems.cfg`. Auto-discovered otherwise. |
| `--config` | path | `config/sources.yaml` | Path to `sources.yaml`. |
| `--systems` | csv | `None` | Restrict to a comma-separated list of system names. |
| `--exclude-systems` | csv | `None` | Comma-separated list of systems to skip. |
| `--workers` | int | `8` | Number of concurrent worker tasks. Mirrors `orchestrator.workers` in `sources.yaml`. |
| `--batch-size` | int | `50` | ROMs per batch. Mirrors `orchestrator.batch_size`. |
| `--match-threshold` | float | `0.7` | Minimum `match_score` to accept a candidate. Mirrors `provider_defaults.match_threshold`. |
| `--hash` | `crc32` \| `sha1` \| `auto` | `auto` | Hash algorithm. `auto` is CRC32 with SHA1 fallback on collision. |
| `--region` | csv | `wor,us,eu,jp` | Region preference order. |
| `--language` | csv | `en` | Default language preference. |
| `--media` | csv | (all) | Subset of `MediaType` values to request. |
| `--no-media` | flag | `false` | Skip media downloads entirely. |
| `--skip-existing` | flag | `false` | Treat cached results as final; do not re-scrape. |
| `--force-rescrape` | flag | `false` | Ignore the cache. |
| `--continue-run` | run id | `None` | Resume an aborted run. The run must be in `aborted` state. |
| `--shutdown-timeout` | int | `180` | Seconds the soft drain waits before forcing cancellation (spec decisión #25). |
| `--provider-cooldown-sec` | int | `1800` | Override `provider_defaults.cooldown_after_blocked_sec`. |
| `--auto-resume-on-unblock` | flag | `false` | Auto-resume a paused run when a provider becomes unblocked. |
| `--ssh-host` | str | `None` | SSH host (overrides `systems.yaml`). |
| `--ssh-user` | str | `None` | SSH user. |
| `--ssh-key` | path | `None` | SSH private key path. |
| `--ssh-port` | int | `22` | SSH port. |
| `--ssh-jump` | str | `None` | ProxyJump host. |
| `--auto-trust` | flag | `false` | Skip strict `known_hosts` check (spec decisión #15). |
| `-v`, `--verbose` | count | `0` | `-v` is DEBUG for `multiscraper.*`; `-vv` also raises library loggers to INFO. |
| `-q`, `--quiet` | flag | `false` | Set `multiscraper.*` to WARNING. |
| `--log-file` | path | `None` | Write JSONL log to this path in addition to the terminal. |
| `--csv` | path | `None` | CSV output path. |
| `--emit` | `es` \| `json` \| `both` | `both` | What to emit at the end of the run. |
| `--dry-run` | flag | `false` | Print a plan and exit without touching disk. |
| `--no-language-columns` | flag | `false` | Skip the `*_language` and `*_source` columns in the CSV. |

### Examples

```bash
# Default run with the example config
multiscraper scrape --config config/sources.yaml

# Only SNES and PSX, 4 workers
multiscraper scrape --systems snes,psx --workers 4

# Resume an aborted run
multiscraper scrape --continue-run 01HXYZ...

# Scrape over SSH
multiscraper scrape \
  --roms-root ssh://pi@192.168.1.42:22/roms \
  --ssh-key ~/.ssh/id_ed25519

# Metadata only, no media
multiscraper scrape --no-media --systems snes

# Dry run, just to see what would happen
multiscraper scrape --dry-run --systems psx
```

## `multiscraper validate-config`

Loads the YAML, resolves `${env:...}` placeholders, and runs the
Pydantic validators. Prints the number of providers and the effective
defaults.

```
multiscraper validate-config [--config PATH] [--es-systems PATH]
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--config` | path | `config/sources.yaml` | Path to `sources.yaml`. |
| `--es-systems` | path | `None` | Optional `es_systems.cfg` to parse. |

Exits `0` on success, `1` if the file is missing or invalid.

## `multiscraper convert-to-es`

Takes a previously cached run and writes `gamelist.xml` files for
each system. Useful when you want to regenerate the XML without
re-running providers.

```
multiscraper convert-to-es --run-id RUN_ID [--out PATH]
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--run-id` | str | (required) | Run identifier (ULID). The run must be in `ok`, `partial`, or `aborted` state with rows in `scrape_results`. |
| `--out` | path | `gamelists` | Output root. Files land in `<out>/<system>/gamelist.xml`. |
| `--systems` | csv | `None` | Restrict to a subset of systems. |

## `multiscraper list-systems`

Lists the systems discovered from `es_systems.cfg` and/or by walking
`roms_root`.

```
multiscraper list-systems [--es-systems PATH] [--roms-root PATH]
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--es-systems` | path | `None` | `es_systems.cfg` to read. |
| `--roms-root` | path | `None` | Local or `ssh://` ROM root. |

## `multiscraper db ...`

Database subcommands operate on `.cache/multiscraper.db`.

```
multiscraper db stats
multiscraper db vacuum
multiscraper db reset              # wipe everything
multiscraper db show-rom <id>      # inspect a single ROM
multiscraper db show-run <run_id>  # inspect a single run
multiscraper db cleanup-runs --keep N
```

| Subcommand | Description |
|---|---|
| `stats` | Print row counts for every table plus the total DB size on disk. |
| `vacuum` | Run `VACUUM` and `ANALYZE` to reclaim space and refresh the query planner. |
| `reset` | Drop and recreate all tables. **Destructive** — confirm with `--yes`. |
| `show-rom` | Pretty-print a `roms` row plus the latest `scrape_results` row. |
| `show-run` | Pretty-print a `runs` row plus aggregate counts by status. |
| `cleanup-runs` | Delete the oldest runs keeping only the N most recent. Use `--dry-run` first. |

## `multiscraper override ...`

Manages the `source_overrides` table used by `local_override` and
`local_fallback`.

```
multiscraper override add <rom_path> [--name NAME] [--image PATH]
multiscraper override list [--system SYSTEM]
multiscraper override remove <rom_path>
multiscraper override import <file.csv>
multiscraper override export <file.csv>
```

| Subcommand | Description |
|---|---|
| `add` | Insert or update an override for a single ROM. The path is the relative path inside the system folder. |
| `list` | List overrides, optionally filtered by system. |
| `remove` | Delete an override by ROM path. |
| `import` | Bulk-import overrides from a CSV with columns `rom_path,name,desc,image_path,...`. |
| `export` | Dump all overrides to a CSV for backup or hand-editing. |

## `multiscraper doctor`

Diagnostic sweep. Reports:

- Python interpreter and version.
- Whether `es_systems.cfg` is found.
- For every enabled provider: whether the required credentials are
  present in the environment.
- SSH reachability for each `ssh_profiles` entry.
- Free disk space in `media_root`.

```
multiscraper doctor
```

Exits `0` if every check passed, `1` otherwise.

### `multiscraper doctor --systems`

When `--systems` is given (comma-separated list), each name is
validated against `es_systems.cfg` (auto-discovered) and
`config/systems.yaml`. Per system, the check reports:

- `source` — where the system was found (`es_systems`, `systems.yaml`,
  or both).
- `name` — `^[a-z0-9_]{1,32}$` enforced.
- `extensions` — **required**. Valid forms:
  - `["*"]` (wildcard; YAML must quote `*` to avoid alias
    interpretation) — `OK`.
  - `[.ext, .ext]` — `OK`.
  - Missing, empty, or items without a leading `.` — `FAIL`.
  If `extensions` is absent from the YAML entry, the value is
  inherited from the matching `es_systems.cfg` row.
- `roms_root` — format-validated. `ssh://<profile>/...`,
  `ssh://<user>@<host>:<port>/...`, `/abs/path`, `~/rel`, `./rel`,
  `../rel` are accepted. Anything else is `FAIL`. The transport is
  inferred from the scheme, so no per-system `ssh_profile` is
  required.

Example:

```
multiscraper doctor --systems snes,gba,nes
```

## Logging flags

`-v`, `-vv`, `-q` are surfaced on every command. The mapping is in
`src/multiscraper/logging_setup.py`:

| Flag | `multiscraper.*` level | Library level |
|---|---|---|
| (default) | `INFO` | `WARNING` |
| `-v` | `DEBUG` | `WARNING` |
| `-vv` | `DEBUG` | `INFO` |
| `-q` | `WARNING` | `WARNING` |

See `docs/logging.md` for the full event vocabulary and JSONL
format.
