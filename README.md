# multiscraper

`multiscraper` is a parallel, multi-source scraper for retro
gaming frontends (EmulationStation, RetroPie, Batocera,
Recalbox). It discovers ROMs from a local folder or a remote
machine over SSH, queries 11 metadata providers in a cascading
fallback chain (ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb,
RetroAchievements, TheGamesDB, LibRetro Thumbnails, OpenVGDB,
GameFAQs, plus a local override and fallback table), downloads
media (cover, marquee, video, box-3D, backcover, fanart, manual,
miximage, logo), and writes EmulationStation-compatible
`gamelist.xml` plus a per-run CSV and a JSONL log. SQLite (WAL)
is used for caching and run resumption. The codebase is asyncio
+ aiohttp throughout, with a supervisor that recovers dead
workers and a graceful drain on SIGTERM.

## Quickstart

```bash
# Install (editable, with dev deps)
git clone https://github.com/fr4j4/multiscraper
cd multiscraper
pip install -e ".[dev]"

# Copy the example config and edit credentials
cp config/sources.example.yaml config/sources.yaml
cp config/systems.example.yaml config/systems.yaml

# At minimum, set the provider credentials you want to use
export SCREENSCRAPER_DEV_ID="your-id"
export SCREENSCRAPER_DEV_PASSWORD="your-pass"

# Validate the config
multiscraper validate-config

# Run against the systems defined in es_systems.cfg
multiscraper scrape
```

The first run creates `.cache/multiscraper.db` (the SQLite cache)
and `~/multiscraper_data/media/` (the media root). Each run
produces `reports/<run_id>/run.csv`, `run.log.jsonl`, and
`summary.json`, plus `gamelists/<system>/gamelist.xml` per
system.

## Features

- **Async core.** Built on `asyncio` + `aiohttp`. 8 workers by
  default, configurable in `sources.yaml`.
- **13 provider entries** — 11 media sources, 1 identifier
  (Hasheous), and a local provider in two roles
  (`local_override` and `local_fallback`).
- **Provider cascade.** Identifies and fetches media by walking
  providers in priority order. First match above
  `match_threshold` wins; others are skipped. Hasheous kicks in
  for name-only failures.
- **SSH transport.** Reads ROMs from a remote arcade without
  downloading them. `asyncssh` under the hood. Keys, agent,
  password, ProxyJump all supported.
- **SQLite cache.** WAL mode, indexed by `system`, `crc32`,
  `sha1`, and `cache_key`. Resumable runs via
  `--continue-run <id>`.
- **EmulationStation output.** `gamelist.xml` per system, with
  the 10 standard media types and the `%Y%m%dT%H%M%S` date
  format. Media files at `media_root/<system>/`.
- **Multi-language metadata.** Field-level priority
  (`text_priority`, `name_priority`) with `best_effort` and
  `strict` fallback strategies. Stopword-based language
  detection by default.
- **Cloudflare-aware blocking.** 3 failures in 60 seconds mark a
  provider as blocked for 30 minutes. `cooldown_after_blocked_sec`
  is configurable.
- **SIGTERM-safe.** Soft drain of `--shutdown-timeout` (180s
  default) before forcing cancellation. `TIMED_OUT` is reported
  as a separate status.
- **Resumable runs.** `--continue-run <id>` re-enqueues
  in-progress and pending jobs without duplicating completed
  rows.
- **CSV per run.** One row per ROM, columns per media type,
  streaming, 50-row flush.
- **JSONL event log.** `run.log.jsonl` with a closed event
  vocabulary for tools.
- **MIT licensed.**

## SSH example

Scrape from a RetroPie box on your LAN without copying the ROMs:

```bash
# Add the host key once
ssh-keyscan -p 22 192.168.1.42 >> ~/.ssh/known_hosts

# Configure systems.yaml
cat > config/systems.yaml <<'EOF'
roms_root: ssh://pi@192.168.1.42:22/home/pi/RetroPie/roms
media_root: ~/multiscraper_data/media

ssh_profiles:
  arcade01:
    host: 192.168.1.42
    port: 22
    user: pi
    key_file: ~/.ssh/id_ed25519
    known_hosts: ~/.ssh/known_hosts
EOF

# Run
multiscraper scrape --systems snes,psx
```

Or inline with CLI flags:

```bash
multiscraper scrape \
  --roms-root ssh://pi@192.168.1.42:22/home/pi/RetroPie/roms \
  --ssh-host 192.168.1.42 \
  --ssh-user pi \
  --ssh-key ~/.ssh/id_ed25519
```

See `docs/ssh-setup.md` for the full guide (keys, agent,
password, ProxyJump, `--auto-trust`).

## Provider list

`multiscraper` ships with these providers (default cascade order
in `config/sources.example.yaml`):

| # | Provider | Type | Auth | Notes |
|---|---|---|---|---|
| 1 | `local_override` | offline | none | Curated local overrides (highest priority). |
| 2 | `hasheous` | identifier | none | Hash -> canonical name fallback. |
| 3 | `screenscraper` | media | optional devid/devpass | Primary retro source. All 10 media types. |
| 4 | `igdb` | media | Twitch OAuth2 | Modern/indie. |
| 5 | `mobygames` | media | api_key | Premium metadata. |
| 6 | `giantbomb` | media | api_key | Gameplay videos. 200/h. |
| 7 | `retroachievements` | media | api_key + username | NES/SNES/Genesis strength. |
| 8 | `rawg` | media | api_key | Massive modern catalog. |
| 9 | `thegamesdb` | media | api_key v2 | Banner + fanart. |
| 10 | `libretro_thumbnails` | offline | none | Probes GitHub raw by name. |
| 11 | `openvgdb` | media | none | HTML scrape, no auth. |
| 12 | `gamefaqs` | media | none | Last-resort descriptions. |
| 13 | `local_fallback` | offline | none | Curated local overrides (last priority). |

See `docs/research/alternatives.md` for a side-by-side
comparison, and `docs/adding-a-provider.md` to add your own.

## Documentation

- `docs/architecture.md` — high-level architecture and
  components.
- `docs/configuration.md` — full YAML reference.
- `docs/cli.md` — every CLI flag with its default.
- `docs/adding-a-provider.md` — how to write a new `Provider`.
- `docs/ssh-setup.md` — SSH configuration and security modes.
- `docs/ems_files.md` — `gamelist.xml` and media file format.
- `docs/logging.md` — terminal and JSONL logging.
- `docs/research/emulationstation.md` — how ES discovers systems
  and reads `gamelist.xml`.
- `docs/research/screenscraper-api.md` — the primary upstream
  API.
- `docs/research/alternatives.md` — comparison of all providers.

## Development

```bash
pip install -e ".[dev]"

# Run tests (no network needed; uses cassettes and fakes)
pytest

# Type-check (strict)
mypy src

# Lint
ruff check src
```

Test markers: `network` (skipped in CI by default) and `slow`.

## License

MIT — see `LICENSE`.
