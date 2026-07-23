# Configuration Reference

`multiscraper` reads two configuration files:

- `config/sources.yaml` (or whatever you pass via `--config`). Drives
  the provider cascade, language preferences, orchestrator tuning, and
  provider defaults. Loaded and validated by
  `src/multiscraper/config/loader.py` into a `MultiscraperConfig`
  Pydantic model (`config/models.py`).
- `config/systems.yaml` (or `--systems-config`). Drives the
  transport: where the ROMs live (local or `ssh://`), where media
  files land, and the SSH profiles to use when reading from a remote
  host.

If you have an `es_systems.cfg` (RetroPie / Batocera / Recalbox),
`multiscraper` auto-discovers it; you do not need a `systems.yaml`.
See `docs/ems_files.md` and the `es_systems_parser` module.

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
  - id: igdb
    priority: 10
    enabled: true
    config:
      client_id: ${env:TWITCH_CLIENT_ID}
      client_secret: ${env:TWITCH_CLIENT_SECRET}
  - id: mobygames
    priority: 15
    enabled: true
    config:
      api_key: ${env:MOBYGAMES_API_KEY}
  - id: giantbomb
    priority: 20
    enabled: true
    config:
      api_key: ${env:GIANTBOMB_API_KEY}
  - id: retroachievements
    priority: 25
    enabled: true
    config:
      username: ${env:RA_USERNAME}
      api_key: ${env:RA_API_KEY}
  - id: rawg
    priority: 30
    enabled: true
    config:
      api_key: ${env:RAWG_API_KEY}
  - id: thegamesdb
    priority: 35
    enabled: true
    config:
      api_key: ${env:TGDB_API_KEY}
  - id: libretro_thumbnails
    priority: 40
    enabled: true
  - id: openvgdb
    priority: 45
    enabled: true
  - id: gamefaqs
    priority: 50
    enabled: true
  - id: local_fallback
    priority: 9999
    enabled: true

provider_defaults:
  rate_limit_per_sec: 2.0
  burst: 1
  cooldown_after_blocked_sec: 1800
  max_consecutive_failures: 3
  timeout_sec: 30
  match_threshold: 0.7
  max_candidates_per_provider: 10
```

### `language` block

`LanguageConfig` (`config/models.py`). Drives field-level language
fallback (spec decisión #31).

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

### `orchestrator` block

`OrchestratorConfig` (`config/models.py`). Tunables for the run.

| Key | Type | Default | Notes |
|---|---|---|---|
| `workers` | int | `8` | Number of concurrent `asyncio.Task` workers. |
| `media_concurrency` | int | `4` | Per-worker parallelism for downloading media. |
| `batch_size` | int | `50` | ROMs per batch. |
| `max_job_attempts` | int | `3` | Per-job retry cap before DLQ. |
| `worker_failure_window_sec` | int | `60` | Sliding window for the worker-quarantine rule. |
| `worker_failure_threshold` | int | `3` | Failures in the window before quarantine. |
| `shutdown_drain_timeout_sec` | int | `180` | Soft drain budget for SIGTERM (spec decisión #25). |
| `csv_flush_every` | int | `50` | Rows buffered between CSV flushes. |
| `progress_interval_sec` | float | `0.5` | Progress reporter tick. |

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
| `rate_limit_per_sec` | float | `2.0` | Token-bucket refill rate (spec decisión #29/30). |
| `burst` | int | `1` | Token-bucket burst. |
| `cooldown_after_blocked_sec` | int | `1800` | How long a blocked provider stays out (spec decisión #29). |
| `max_consecutive_failures` | int | `3` | Failures in a row before marking as blocked. |
| `timeout_sec` | float | `30.0` | HTTP timeout per request. |
| `match_threshold` | float | `0.7` | Minimum `match_score` to accept a candidate (spec decisión #28). |
| `max_candidates_per_provider` | int | `10` | Cap on candidates returned per provider per ROM (spec decisión #30). |

## `systems.yaml`

Example (`config/systems.example.yaml`):

```yaml
roms_root: ~/ROMs                      # local path or ssh://user@host:port/path
media_root: ~/multiscraper_data/media  # where to save downloaded media

ssh_profiles:
  arcade01:
    host: 192.168.1.42
    port: 22
    user: pi
    key_file: ~/.ssh/id_ed25519
    # password: ${env:ARCADE_SSH_PASS}
    known_hosts: ~/.ssh/known_hosts
    # jump_host: user@bastion.local

# Override es_systems.cfg path (auto-discovered by default)
# es_systems_path: ~/.emulationstation/es_systems.cfg
```

| Key | Type | Default | Notes |
|---|---|---|---|
| `roms_root` | str (path or `ssh://` URL) | (required) | Where to look for ROMs. The transport is selected by URL scheme. |
| `media_root` | str (path) | `$HOME/multiscraper_data/media/` | Per spec decisión #24. The CLI flag `--media-root` overrides this. |
| `ssh_profiles` | map[str, profile] | `{}` | One named profile per remote host. Reference by URL `ssh://<profile>@host`. |
| `es_systems_path` | str (path) | auto-discovered | Explicit path to `es_systems.cfg`. |

### SSH profile fields

| Key | Type | Default | Notes |
|---|---|---|---|
| `host` | str | (required) | Hostname or IP. |
| `port` | int | `22` | SSH port. |
| `user` | str | OS user | SSH user. |
| `key_file` | str (path) | — | Path to a private key. If omitted, the agent is consulted. |
| `password` | str | — | Plain password (prefer `key_file` or agent). |
| `known_hosts` | str (path) | `~/.ssh/known_hosts` | Strict host key check. |
| `jump_host` | str | — | ProxyJump target. |

See `docs/ssh-setup.md` for the full SSH flow including the
`--auto-trust` flag and the security implications.

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
`es_systems.cfg` takes precedence for the per-system block
(spec decisión #4). `systems.yaml` still owns the transport
(`roms_root`, `ssh_profiles`, `media_root`).

## Environment variable resolution

Any string value in the YAML can contain `${env:VAR_NAME}`
placeholders. They are resolved by `resolve_env_vars` in
`config/loader.py` at load time. Missing variables resolve to the
empty string; this is a soft failure, not a hard one. The user is
expected to spot it on the first `multiscraper validate-config` run.

Examples in the example config:

```yaml
devid: ${env:SCREENSCRAPER_DEV_ID}
api_key: ${env:MOBYGAMES_API_KEY}
password: ${env:ARCADE_SSH_PASS}
```

The substitution is recursive: it walks into nested dicts and lists.
A literal `$` must be escaped as `$$`. The placeholder regex is
`\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}` so the variable name must start
with a letter or underscore.

## Validation

Run `multiscraper validate-config` to load the YAML, resolve env
vars, and run the Pydantic validator. A failure prints the offending
field and the human-readable error.
