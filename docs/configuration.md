# Configuration Reference

`multiscraper` reads three configuration files:

- `config/config.yaml` — transports, `current_transport`, `defaults`,
  and `orchestrator`. Loaded into a `TransportsConfig` Pydantic model
  (`config/models.py`).
- `config/systems.yaml` — declarative systems with `relative_path` or
  `full_path` (exactly one). Loaded into a `SystemsConfig` Pydantic
  model.
- `config/sources.yaml` — provider cascade, language preferences,
  output format, and provider defaults. Loaded into a
  `MultiscraperConfig` Pydantic model.

If you have an `es_systems.cfg` (RetroPie / Batocera / Recalbox),
`multiscraper` auto-discovers it; you do not need a `systems.yaml`.
See `docs/ems_files.md` and the `es_systems_parser` module.

## `config.yaml`

Example (`config/config.yaml.example`):

```yaml
transports:
  - name: arcade
    kind: ssh
    host: 192.168.1.28
    port: 22
    user: arcade
    password: ${env:ARCADE_PASS}
    auto_trust: true
    base_path: /home/arcade/ROMs

  - name: workstation
    kind: local
    base_path: /home/user/roms

current_transport: arcade

defaults:
  media_root: ~/multiscraper_data/media
  cache_db: ~/.multiscraper/cache.db

orchestrator:
  workers: 8
  media_concurrency: 4
  batch_size: 50
  max_job_attempts: 3
  worker_failure_window_sec: 60
  worker_failure_threshold: 3
  shutdown_drain_timeout_sec: 180
  csv_flush_every: 50
  progress_interval_sec: 0.5
```

### `transports` list

Each entry is a `Transport`. The transport is the bridge between
systems (logical) and the actual ROM files. Exactly one transport
must be selected via `current_transport`.

| Key | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Lowercase slug (`^[a-z0-9_]{1,32}$`). Used in `current_transport` and as a `transport[<name>]` doctor check label. |
| `kind` | `ssh` \| `local` | yes | Determines how ROMs are read. |
| `base_path` | str | **yes** | Root directory the transport reads from. Systems reference this with `relative_path` (concatenated) or override with `full_path`. |
| `host` | str | for `ssh` | Hostname or IP. |
| `port` | int | no (default `22`) | SSH port. |
| `user` | str | for `ssh` | SSH user. |
| `password` | str | no | Plain password (prefer `key_file` or agent). |
| `key_file` | str | no | Path to a private key. |
| `known_hosts` | str | no | Path to known_hosts file. |
| `auto_trust` | bool | no | Auto-trust unknown host keys. |

### `current_transport`

The single transport that is currently active. Must match a
`transports[].name`. If you have a laptop and a NAS, you flip the
active transport by editing this field; no other config needs to
change.

### `defaults`

`defaults` is a free-form `dict` consumed by the orchestrator and
output modules. The conventional keys are:

| Key | Type | Default | Notes |
|---|---|---|---|
| `media_root` | str (path) | `~/multiscraper_data/media` | Where downloaded media lands. |
| `cache_db` | str (path) | `~/.multiscraper/cache.db` | SQLite cache location. |

### `orchestrator`

`OrchestratorConfig` (`config/models.py`). Tunables for the run.

| Key | Type | Default | Notes |
|---|---|---|---|
| `workers` | int | `8` | Number of concurrent `asyncio.Task` workers. |
| `media_concurrency` | int | `4` | Per-worker parallelism for downloading media. |
| `batch_size` | int | `50` | ROMs per batch. |
| `max_job_attempts` | int | `3` | Per-job retry cap before DLQ. |
| `worker_failure_window_sec` | int | `60` | Sliding window for the worker-quarantine rule. |
| `worker_failure_threshold` | int | `3` | Failures in the window before quarantine. |
| `shutdown_drain_timeout_sec` | int | `180` | Soft drain budget for SIGTERM. |
| `csv_flush_every` | int | `50` | Rows buffered between CSV flushes. |
| `progress_interval_sec` | float | `0.5` | Progress reporter tick. |

## `systems.yaml`

Example (`config/systems.example.yaml`):

```yaml
systems:
  - name: snes
    relative_path: /snes
    extensions: [sfc, smc]

  - name: gba
    relative_path: /gba
    extensions: [gba]

  - name: psx
    full_path: /mnt/external/roms/psx
    extensions: [cue, bin, iso]
```

### Per-system `systems` entries

| Key | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Must match `^[a-z0-9_]{1,32}$`. |
| `extensions` | list[str] | **yes** | Wildcard `["*"]` or a list like `[gba, gb]`. Leading dot is optional. |
| `relative_path` | str | exactly one of these | Concatenated with the current transport's `base_path`. |
| `full_path` | str | exactly one of these | Used as-is, ignoring `base_path`. |

### Path resolution

When the orchestrator needs the ROMs for a system, the doctor (and
the orchestrator) resolve the path with this rule:

- `full_path` wins — used as-is, ignoring `base_path`.
- `relative_path` is concatenated with the current transport's
  `base_path` with exactly one `/` between them, even if one side
  already has a separator. The base's trailing `/` is stripped and a
  leading `/` is added to the relative path if missing.

For example, with `base_path: /home/arcade/ROMs`:

| `relative_path` | resolved |
|---|---|
| `/snes` | `/home/arcade/ROMs/snes` |
| `snes` | `/home/arcade/ROMs/snes` |
| `/` | `/home/arcade/ROMs/` |

### Accessibility check

The doctor verifies the resolved path is reachable. For
`kind=local`, the path must exist. For `kind=ssh`, an SSH
connection is opened and the base path is `ls`-ed.

## `sources.yaml`

Example (`config/sources.example.yaml`):

```yaml
language:
  text_priority: [en, es, fr, de, it, pt, jp]
  name_priority: [en, es, jp, fr]
  fallback_strategy: best_effort
  default_language: en
  detection_method: stopwords

output:
  csv_include_language_columns: true
  partial_min_media: 3
  required_media_types: [image]

providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: hasheous
    kind: identifier
    enabled: true
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SCREENSCRAPER_DEV_ID}
      devpassword: ${env:SCREENSCRAPER_DEV_PASSWORD}
      region_priority: [wor, us, eu, jp]
      language_priority: [en, es, fr]
  - id: local_fallback
    priority: 9999
    enabled: true

provider_defaults:
  rate_limit_per_sec: 2.0
  burst: 1
  cooldown_after_blocked_sec: 1800
  max_consecutive_failures: 3
  timeout_sec: 30.0
  match_threshold: 0.7
  max_candidates_per_provider: 10
```

Note: the `orchestrator:` block previously in this file has moved to
`config.yaml`. Sources.yaml is now strictly provider cascade +
language + output + provider defaults.

### `language` block

`LanguageConfig` (`config/models.py`). Drives field-level language
fallback.

| Key | Type | Default | Notes |
|---|---|---|---|
| `text_priority` | list[str] | `["en"]` | Ordered list used for `desc` and `genre`. |
| `name_priority` | list[str] | `["en"]` | Ordered list used for `name`. |
| `fallback_strategy` | `best_effort` \| `strict` | `best_effort` | `best_effort` keeps the first non-empty value; `strict` errors if `name_priority[0]` is not satisfied. |
| `default_language` | str | `en` | Used when detection fails. |
| `detection_method` | `stopwords` \| `langdetect` \| `trust_provider` | `stopwords` | Heuristic for untagged text. |

### `output` block

`OutputConfig` (`config/models.py`). Drives CSV and OK/PARTIAL
promotion.

| Key | Type | Default | Notes |
|---|---|---|---|
| `csv_include_language_columns` | bool | `true` | Adds `name_language`, `desc_language`, `genre_language`, `desc_source`, `genre_source` columns. |
| `partial_min_media` | int | `3` | Minimum number of media files to promote a result to `OK`. |
| `required_media_types` | list[str] | `["image"]` | These types MUST be present for `OK`. |

### `providers` list

Each entry is a `ProviderEntry`. The cascade consults `priority`
in ascending order. `local_override` is conventionally `1`,
`local_fallback` is conventionally `9999`.

| Key | Type | Default | Notes |
|---|---|---|---|
| `id` | str | (required) | One of: `local_override`, `local_fallback`, `hasheous`, `screenscraper`, `igdb`, `rawg`, `mobygames`, `giantbomb`, `retroachievements`, `thegamesdb`, `libretro_thumbnails`, `openvgdb`, `gamefaqs`. Third-party provider IDs are also accepted. |
| `kind` | `media` \| `identifier` | `media` | `identifier` is for sources that only resolve hash -> canonical name (e.g. `hasheous`). |
| `priority` | int | `100` | Lower runs first. |
| `enabled` | bool | `true` | If false, the entry is skipped. |
| `config` | dict | `{}` | Provider-specific keys (see below). |

#### Provider-specific config

- `screenscraper`:
  - `devid`, `devpassword` (recommended for higher rate limits).
  - `region_priority: list[str]` (default `["wor","us","eu","jp"]`).
  - `language_priority: list[str]` (default `["en"]`).
- `igdb`:
  - `client_id`, `client_secret` (Twitch OAuth2 credentials).
- `mobygames`:
  - `api_key`.
- `giantbomb`:
  - `api_key`.
- `retroachievements`:
  - `username`, `api_key`.
- `rawg`:
  - `api_key`.
- `thegamesdb`:
  - `api_key` (v2).
- `hasheous`, `local_override`, `local_fallback`,
  `libretro_thumbnails`, `openvgdb`, `gamefaqs` take no config
  block (or empty).

### `provider_defaults` block

`ProviderDefaults` (`config/models.py`). Applied to every provider
that does not override the value.

| Key | Type | Default | Notes |
|---|---|---|---|
| `rate_limit_per_sec` | float | `2.0` | Token-bucket refill rate. |
| `burst` | int | `1` | Token-bucket burst. |
| `cooldown_after_blocked_sec` | int | `1800` | How long a blocked provider stays out. |
| `max_consecutive_failures` | int | `3` | Failures in a row before marking as blocked. |
| `timeout_sec` | float | `30.0` | HTTP timeout per request. |
| `match_threshold` | float | `0.7` | Minimum `match_score` to accept a candidate. |
| `max_candidates_per_provider` | int | `10` | Cap on candidates returned per provider per ROM. |

## `es_systems.cfg` auto-discovery

If `--es-systems` is not given, the loader looks in this order:

1. `./es_systems.cfg`
2. `$HOME/.emulationstation/es_systems.cfg`
3. `~/.emulationstation/es_systems.cfg`
4. `config/es_systems.cfg`

When found, `config/es_systems_parser.py` extracts the `<system>`
elements with `<name>`, `<fullname>`, `<path>`, `<extension>`,
`<command>`, `<platform>`, `<theme>`. The `<extension>` field is
split on whitespace to produce the list of accepted file extensions
per system. The parser ignores `<system>` entries with no `<name>`.

If both `systems.yaml` and `es_systems.cfg` are present, the
`es_systems.cfg` takes precedence for the per-system block.
`systems.yaml` still owns the transport-relevant fields
(`relative_path` / `full_path`) when present.

## Environment variable resolution

Any string value in any of the three YAMLs can contain
`${env:VAR_NAME}` placeholders. They are resolved by
`resolve_env_vars` in `config/loader.py` at load time. Missing
variables resolve to the empty string; this is a soft failure, not
a hard one. The user is expected to spot it on the first
`multiscraper validate-config` run.

The substitution is recursive: it walks into nested dicts and lists.
The placeholder regex is `\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}` so the
variable name must start with a letter or underscore.

## Validation

Run `multiscraper validate-config` to load the three YAMLs, resolve
env vars, and run the Pydantic validators. A failure prints the
offending field and the human-readable error.
