# Data Providers

`multiscraper` ships with 13 provider entries: 11 distinct media sources, 1 identifier source (`hasheous`), and the local provider in two roles (`local_override` and `local_fallback`). This document details each provider's API, auth, rate limits, metadata/media coverage, and configuration, plus alternative data sources not implemented in the project.

## Overview

"Priority" is the cascade priority (lower runs first). "Default" refers to `config/sources.example.yaml`.

| # | Provider | Priority | Type | Auth | Media Types | Rate Limit | Default |
|---|---|---|---|---|---|---|---|
| 1 | `local_override` | 1 | media, offline | none | all 10 | N/A | yes |
| 2 | `hasheous` | 7 | identifier | none | N/A | 2 req/s | yes |
| 3 | `screenscraper` | 5 | media | devid+devpassword (optional) | all 10 | 2 req/s | yes |
| 4 | `igdb` | 10 | media | Twitch OAuth2 | image, thumb, video | 4 req/s | no |
| 5 | `mobygames` | 15 | media | api_key | image, thumb, screenshot | 1 req/s | no |
| 6 | `giantbomb` | 20 | media | api_key | image, thumb, video | 200/h | no |
| 7 | `retroachievements` | 25 | media | username + api_key | image, logo | 1 req/s | no |
| 8 | `rawg` | 30 | media | api_key | image, thumb | 5 req/s | no |
| 9 | `thegamesdb` | 35 | media | api_key v2 | image, thumb | 1 req/s | no |
| 10 | `libretro_thumbnails` | 40 | media, offline | none | image, box3d, logo | 0.5 req/s | no |
| 11 | `openvgdb` | 45 | media | none | image | 1 req/s | no |
| 12 | `gamefaqs` | 50 | media | none | image | 0.5 req/s | no |
| 13 | `local_fallback` | 9999 | media, offline | none | all 10 | N/A | yes |

## Provider Cascade

The cascade runs providers in priority order. The first provider to return a candidate above `match_threshold` (default 0.7) wins.

### Two phases

1. **Identification**: Each non-identifier provider is queried by name (or hash if available). The best candidate above threshold stops the search.
2. **Media**: For each wanted `MediaType`, providers that support that type are tried in priority order. The first provider returning a URL for that type wins.

### Block detection

When a provider returns HTTP 403, 503, or 429 (or a body containing Cloudflare challenge keywords, captcha pages, or "are you human" prompts), it is placed in a 30-minute cooldown (`cooldown_after_blocked_sec: 1800`). The token-bucket rate limiter per provider prevents bursts from reaching the upstream.

### Identifier providers

`hasheous` runs as an identifier (not a media provider). When identification by name fails, the cascade can use `hasheous` to look up a canonical name by hash, then re-query the other providers with that name.

### Provider defaults

Global defaults from `config/sources.yaml` (`provider_defaults`):

| Setting | Default | Description |
|---------|---------|-------------|
| `rate_limit_per_sec` | 2.0 | Max requests per second |
| `burst` | 1 | Allowed burst above rate limit |
| `cooldown_after_blocked_sec` | 1800 | Cooldown duration (30 min) |
| `max_consecutive_failures` | 3 | Block after this many failures |
| `timeout_sec` | 30 | HTTP timeout |
| `match_threshold` | 0.7 | Minimum score to stop cascade |
| `max_candidates_per_provider` | 10 | Candidates per provider |

## Provider Details

### `local_override` (priority 1)

- **Type:** offline, no network.
- **Source:** SQLite `source_overrides` table (managed via `multiscraper override ...`).
- **Auth:** none.
- **Media:** all 10 `MediaType` values.
- **Behavior:** returns at most one `Candidate` with `match_score=1.0`. The cascade stops on it immediately.
- **Use case:** user-curated metadata overrides for specific ROMs. Hand-fixed data takes precedence over any network provider.
- **Source file:** `src/multiscraper/providers/local.py`.

### `hasheous` (priority 7)

- **Type:** identifier (not a media provider).
- **Source:** `https://hasheous.org/api/v1/hasheous/lookup/<hash>`.
- **Auth:** none.
- **Used:** when the media cascade failed to find a match by name. The result is a canonical name that the cascade re-uses to re-query other providers.
- **API docs:** `hasheous.org/swagger`.
- **Notes:** uses SHA1 if available, otherwise CRC32. Returns `IdentifierResult` with `canonical_name`, `platform`, `source_id`, `confidence=0.8`. No media support — purely for name resolution.
- **Source file:** `src/multiscraper/providers/hasheous.py`.

### `screenscraper` (priority 5)

- **Type:** media.
- **Source:** ScreenScraper.fr API v2, base URL `https://www.screenscraper.fr/api2`.
- **Endpoint:** `GET /jeuInfos.php` — main metadata + media lookup.
- **Auth:** optional `devid` + `devpassword` (and optional `ssid` + `sspassword` for user-mode). Lifts the daily quota from ~5,000 to ~50,000 calls.
- **Media:** all 10 `MediaType` values — the only provider with full coverage.
- **Rate limit:** 2 req/s (authenticated), ~1 req/s (unauthenticated). Daily quota resets at midnight France time.
- **Format:** XML. Top-level `<Data>` with `<jeu>` (success) or `<erreur>` (error).
- **Metadata:** name (multilingual), synopsis, release date, developer, publisher, genres, players, rating.
- **Media mapping:**

| ScreenScraper type | multiscraper MediaType |
|--------------------|----------------------|
| `box2D`, `box2D-side` | `IMAGE` (cover) |
| `ss` | `THUMBNAIL` (screenshot) |
| `video` | `VIDEO` |
| `screenmarquee`, `wheel` | `MARQUEE` |
| `box-3D` | `BOX3D` |
| `box2D-back` | `BACKCOVER` |
| `fanart` | `FANART` |
| `manuel` | `MANUAL` |
| `mixrbv1` | `MIXIMAGE` |
| `logo` | `LOGO` |

- **Query params:** `devid`, `devpassword`, `softname` (always `multiscraper`), `crc`, `sha1`, `romname`, `romtaille` (file size), `systemeid` (numeric platform id), `romtype` (`rom`/`iso`/`disc`), `media` (comma-separated types), `region`, `langue`.
- **Region/language:** configurable in `sources.yaml` via `region_priority` and `language_priority` arrays. The provider walks each list in order and stops on the first non-empty hit.
- **Platform map:** numeric ids (e.g. SNES=4, NES=3, N64=14, megadrive=1) in `_PLATFORM_MAP` in `screenscraper.py`. 40+ platforms mapped.
- **Blocking:** Cloudflare challenge at high request rates. Detected by `block_detect.py` via `<erreur>` XML or HTTP 403/503/429.
- **Config example:**

```yaml
providers:
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SCREENSCRAPER_DEV_ID}
      devpassword: ${env:SCREENSCRAPER_DEV_PASSWORD}
      region_priority: [wor, esp, us, eu, jp]
      language_priority: [es, en, fr]
```

- **Strengths:** most complete retro database. Best for NES, SNES, Genesis, arcade, and pre-2010 platforms. Multilingual.
- **Weaknesses:** aggressive rate limiting. Cloudflare challenge if exceeded. Cold start without credentials gets blocked easily.
- **Source file:** `src/multiscraper/providers/screenscraper.py`.
- **See also:** `docs/research/screenscraper-api.md`.

### `igdb` (priority 10)

- **Type:** media.
- **Source:** Internet Game Database, via Twitch. Base URL: `https://api.igdb.com/v4`.
- **Auth:** Twitch OAuth2 (`client_id` + `client_secret`). Token expires in ~24 hours, auto-refreshed. POST to `https://id.twitch.tv/oauth2/token` with `grant_type=client_credentials`.
- **Rate limit:** 4 req/s, 8 concurrent connections. 50,000 requests/month, resets 1st of month UTC. HTTP 429 if exceeded.
- **Format:** JSON. Uses POST with APICalypse query language in the body.
- **Endpoint:** `POST /v4/games` with body like `fields name,summary,rating,genres.name,platforms.name,cover.image_id,screenshots.image_id; search "<name>"; platforms = (<id>); limit 10;`
- **Media:** `IMAGE` (cover), `THUMBNAIL` (cover thumb + first screenshot). Image URLs built from `https://images.igdb.com/igdb/image/upload/t_cover_big/<image_id>.jpg`.
- **Metadata:** name, summary, release date, developer, publisher, genres, rating (scaled /10), aggregated rating count, platforms.
- **Platform map:** numeric ids (e.g. SNES=19, NES=18, N64=4, megadrive=29, PSX=7) in `_PLATFORM_MAP` in `igdb.py`. 20+ platforms mapped.
- **Config example:**

```yaml
providers:
  - id: igdb
    priority: 10
    enabled: false
    config:
      client_id: ${env:TWITCH_CLIENT_ID}
      client_secret: ${env:TWITCH_CLIENT_SECRET}
```

- **Strengths:** best database for modern and indie games. Free for non-commercial use under Twitch Developer Service Agreement. 500,000+ games. Data dumps available via partnership.
- **Weaknesses:** English-only text. Weak retro coverage (mostly post-1995). Slow token refresh on cold start. Commercial use requires partnership (`partner@igdb.com`).
- **API docs:** [api-docs.igdb.com](https://api-docs.igdb.com/).
- **Source file:** `src/multiscraper/providers/igdb.py`.

### `mobygames` (priority 15)

- **Type:** media.
- **Source:** MobyGames API v1. Base URL: `https://api.mobygames.com/v1`.
- **Endpoints:** `GET /v1/games?title=<name>&api_key=<key>` (search), `GET /v1/games/{id}/covers?api_key=<key>` (cover art).
- **Auth:** `api_key`. **Paid since September 2024** — legacy free keys still work but are limited.
- **Rate limit:** 1 req/s, 720 req/hour per method.
- **Format:** JSON.
- **Media:** `IMAGE` (first cover), `THUMBNAIL` (same cover).
- **Metadata:** title, description, release date, developer, publisher, genres, players, rating, credits.
- **Platform map:** numeric ids (e.g. SNES=15, NES=23, N64=10, megadrive=16, PSX=6) in `_PLATFORM_MAP` in `mobygames.py`. 13 platforms mapped.
- **Config example:**

```yaml
providers:
  - id: mobygames
    priority: 15
    enabled: false
    config:
      api_key: ${env:MOBYGAMES_API_KEY}
```

- **Strengths:** highest-quality metadata for commercial games. Excellent for 1970s-2000s. Credits info. Community-curated.
- **Weaknesses:** only ~30% of games have cover art. Slow. Now paid (subscription required as of Sep 2024).
- **API docs:** [mobygames.com/info/api](https://www.mobygames.com/info/api/).
- **Source file:** `src/multiscraper/providers/mobygames.py`.

### `giantbomb` (priority 20)

- **Type:** media.
- **Source:** Giant Bomb API. Base URL: `https://www.giantbomb.com/api`.
- **Endpoint:** `GET /api/games/?api_key=<key>&filter=name:<name>&format=json&limit=10`.
- **Auth:** `api_key`.
- **Rate limit:** 200 req/resource/hour (separate counters per endpoint). HTTP 420 "Enhance Your Calm" when exceeded. Effective 0.05 req/s.
- **Format:** JSON.
- **Media:** `IMAGE` (`image.screen_url`), `THUMBNAIL` (`image.thumb_url`), `VIDEO` (`video.site_detail_url`).
- **Metadata:** name, deck (short description), description, release date, developer, publisher, genres, platforms.
- **Platform map:** string slugs (e.g. `snes`, `nes`, `n64`, `genesis`, `ps1`) in `_PLATFORM_MAP` in `giantbomb.py`. 18 platforms mapped.
- **Config example:**

```yaml
providers:
  - id: giantbomb
    priority: 20
    enabled: false
    config:
      api_key: ${env:GIANTBOMB_API_KEY}
```

- **Strengths:** real gameplay videos for many titles. Good wiki metadata. Rich editorial content.
- **Weaknesses:** tightest rate limit of all providers (200/hour). Skip for large runs. Videos are page URLs, not direct media files.
- **API docs:** [giantbomb.com/api](https://www.giantbomb.com/api/).
- **Source file:** `src/multiscraper/providers/giantbomb.py`.

### `retroachievements` (priority 25)

- **Type:** media.
- **Source:** RetroAchievements API. Base URL: `https://retroachievements.org/API`.
- **Endpoint:** `GET /API/API_GetGameList.php?z=<username>&y=<api_key>&i=10&f=1` (global game list).
- **Auth:** `username` + `api_key` (web API key from RA profile, not a console token). Passed as `z` and `y` query params.
- **Rate limit:** 1 req/s. No official cap documented, but rate limiting is enabled. Cache recommended.
- **Format:** JSON.
- **Media:** `IMAGE` (`ImageIcon` field), `LOGO` (`ImageTitle` field). Images served from `retroachievements.org`.
- **Metadata:** name, description, developer, publisher, genre, release date, players, rating (from achievement set data).
- **Platform map:** numeric ids (e.g. SNES=3, NES=7, N64=2, megadrive=1, PSX=12) in `_PLATFORM_MAP` in `retroachievements.py`. 17 platforms mapped.
- **Config example:**

```yaml
providers:
  - id: retroachievements
    priority: 25
    enabled: false
    config:
      username: ${env:RA_USERNAME}
      api_key: ${env:RA_API_KEY}
```

- **Strengths:** unmatched for classic 8/16-bit era. Curated metadata tied to achievement sets. Active community.
- **Weaknesses:** coverage drops after PS1/N64. No video. Requires free RetroAchievements account.
- **API docs:** [api-docs.retroachievements.org](https://api-docs.retroachievements.org/).
- **Source file:** `src/multiscraper/providers/retroachievements.py`.

### `rawg` (priority 30)

- **Type:** media.
- **Source:** RAWG.io API. Base URL: `https://api.rawg.io/api`.
- **Endpoint:** `GET /api/games?key=<key>&search=<name>&page_size=10`.
- **Auth:** `api_key` (request from rawg.io/apidocs). Free tier available.
- **Rate limit:** 5 req/s. 20,000 requests/month on the free tier. 50,000 on Business ($149/mo). 1,000,000 on Enterprise.
- **Format:** JSON. Paginated.
- **Media:** `IMAGE` (`background_image`), `THUMBNAIL` (same `background_image`).
- **Metadata:** name, description, rating, genres, release date, platforms, ESRB rating, Metacritic, playtime, developers, publishers.
- **Platform map:** string slugs (e.g. `snes`, `nes`, `nintendo-64`, `genesis`, `playstation`) in `_PLATFORM_MAP` in `rawg.py`. 21 platforms mapped.
- **Config example:**

```yaml
providers:
  - id: rawg
    priority: 30
    enabled: false
    config:
      api_key: ${env:RAWG_API_KEY}
```

- **Strengths:** 500,000+ games. Modern and indie coverage is excellent. Highest throughput of the API providers. 2.1M screenshots. Attribution required ("Powered by RAWG.io").
- **Weaknesses:** weak retro coverage. English-only text. Free tier is non-commercial only. No data redistribution allowed.
- **API docs:** [api.rawg.io/docs](https://api.rawg.io/docs/).
- **Source file:** `src/multiscraper/providers/rawg.py`.

### `thegamesdb` (priority 35)

- **Type:** media.
- **Source:** TheGamesDB v2 API. Base URL: `https://api.thegamesdb.net/v2`.
- **Endpoint:** `GET /v2/Games/ByGameName?apikey=<key>&name=<name>`.
- **Auth:** `api_key` (v2, request from thegamesdb.net). Monthly allowance.
- **Rate limit:** 1 req/s.
- **Format:** JSON. Response nested under `data.games`.
- **Media:** `IMAGE`, `THUMBNAIL`. Currently returns candidates with empty media lists (media fetching not implemented in v1 of the provider).
- **Metadata:** name, game_id. Limited metadata in current implementation.
- **Platform map:** numeric ids (e.g. SNES=6, NES=7, N64=3, megadrive=1, PSX=10) in `_PLATFORM_MAP` in `thegamesdb.py`. 12 platforms mapped.
- **Config example:**

```yaml
providers:
  - id: thegamesdb
    priority: 35
    enabled: false
    config:
      api_key: ${env:TGDB_API_KEY}
```

- **Strengths:** same community as the legacy v1, with a redesigned API. The only provider with `banner` art. Good fanart. CDN at `cdn.thegamesdb.net`.
- **Weaknesses:** v2 is still marked experimental by upstream; field names changed without notice in past releases. Media fetching not yet implemented in the provider.
- **API docs:** [thegamesdb.net](https://thegamesdb.net/).
- **Source file:** `src/multiscraper/providers/thegamesdb.py`.

### `libretro_thumbnails` (priority 40)

- **Type:** media, offline (no API).
- **Source:** probes the [libretro-thumbnails](https://github.com/libretro-thumbnails) GitHub repo by name. Uses `raw.githubusercontent.com` raw URLs.
- **Auth:** none.
- **Endpoint:** HEAD probes to `https://raw.githubusercontent.com/libretro-thumbnails/<system>/master/<folder>/<name>.png`.
- **Rate limit:** 0.5 req/s (file download, not API call).
- **Media:** `IMAGE` (Named_Snaps), `BOX3D` (Named_Boxarts), `LOGO` (Named_Titles), `IMAGE` (Standard_Boxarts).
- **Patterns probed:**

| Folder | MediaType | Ext |
|--------|-----------|-----|
| `Named_Snaps` | `IMAGE` | png |
| `Named_Boxarts` | `BOX3D` | png |
| `Named_Titles` | `LOGO` | png |
| `Standard_Boxarts` | `IMAGE` | png |

- **Name normalization:** spaces replaced with underscores.
- **Behavior:** returns at most one `Candidate` with `match_score=1.0` if at least one probe succeeds.
- **CDN:** `thumbnails.libretro.com` also serves these images.
- **Config example:** no config needed.

```yaml
providers:
  - id: libretro_thumbnails
    priority: 40
    enabled: false
```

- **Strengths:** very stable, no auth, no rate limit. High quality art for the systems that libretro supports.
- **Weaknesses:** name match is required (no hash). Coverage is uneven — some systems are great, others are nearly empty. Only 3 media types.
- **Source file:** `src/multiscraper/providers/libretro_thumbnails.py`.

### `openvgdb` (priority 45)

- **Type:** media.
- **Source:** HTML scraping at [vgdb.io](https://vgdb.io/). `GET /search?q=<name>`.
- **Auth:** none.
- **Rate limit:** 1 req/s.
- **Format:** HTML, parsed with lxml.
- **Media:** `IMAGE` only (placeholder cover URL: `<base>/game/<id>/cover.png`).
- **Metadata:** name (extracted from `<a class="game">` links). No other metadata fields populated.
- **Behavior:** parses search results HTML, extracts game links, builds cover URL placeholder.
- **Config example:** no config needed.

```yaml
providers:
  - id: openvgdb
    priority: 45
    enabled: false
```

- **Strengths:** another fallback for hashes. No auth needed. Can also use the OpenVGDB SQLite DB directly as an alternative.
- **Weaknesses:** HTML scraping is fragile; the upstream does not publish an API. Cover URL is a placeholder. Minimal metadata.
- **Source file:** `src/multiscraper/providers/openvgdb.py`.

### `gamefaqs` (priority 50)

- **Type:** media (last-resort HTML scraping).
- **Source:** HTML scraping of [gamefaqs.gamespot.com](https://gamefaqs.gamespot.com/). `GET /search?game=<name>`.
- **Auth:** none.
- **Rate limit:** 0.5 req/s.
- **Format:** HTML, parsed with lxml.
- **Media:** `IMAGE` only (placeholder cover URL).
- **Metadata:** name, description (fetched by following the first result link and parsing `<p class="desc">`).
- **Behavior:** searches, follows first result link, fetches description from game page.
- **Config example:** no config needed.

```yaml
providers:
  - id: gamefaqs
    priority: 50
    enabled: false
```

- **Strengths:** last-resort source of long-form descriptions. Large catalog.
- **Weaknesses:** Cloudflare challenge is common. The "are-you-human" redirect is detected by `block_detect.detect_blocked` and triggers a 30-minute cooldown. Cover URL is a placeholder (likely 404). Only returns first result.
- **Source file:** `src/multiscraper/providers/gamefaqs.py`.

### `local_fallback` (priority 9999)

- **Type:** offline, no network.
- **Source:** same `source_overrides` table as `local_override`, same `LocalProvider` class.
- **Auth:** none.
- **Media:** all 10 `MediaType` values (whatever the user uploaded).
- **Behavior:** runs **after** every other provider. If the cascade produced no candidate above `match_threshold`, this provider scans the override table and returns the best match by `confidence` (default 1.0).
- **Use case:** catch-all for ROMs that no online provider can match, using user-curated local data.
- **Source file:** `src/multiscraper/providers/local.py`.

## Alternative Data Sources

These sources are not implemented in `multiscraper` but are relevant for anyone building a retro game scraping pipeline.

### APIs and services

| Source | Type | Auth | Coverage | Notes |
|--------|------|------|----------|-------|
| **REG-Vault** | REST API + MCP | none (public) | 91,193 games, 99 systems | Multilanguage. Box art, screenshots, videos. URL: `reg.vault.rip` |
| **Nostalgia Lab** | GraphQL API + SQLite downloads | API key (free) | 45 platforms | SQLite DB downloadable per platform. URL: `nostalgia-lab.com` |
| **LaunchBox Games DB** | XML DB (downloadable) | none | Complete | Matches by exact filename. Used by LaunchBox/BigBox frontends. URL: `launchbox-app.com` |
| **Playmatch** | Hash matching | none | Open source | Community-driven. Proxies IGDB/ScreenScraper/etc. URL: `playmatch.com` |
| **SteamGridDB** | REST API | API key | Custom covers | Cover art, logos, icons, hero images. No game metadata. URL: `www.steamgriddb.com` |
| **Moral Video Game Library** | SQLite DB | none | 79,882 games | Filtered by "abandonware". Open source. |
| **shiragame** | SQLite DB | none | Compiled DATs | Compiles No-Intro/Redump/TOSEC DATs. Updated 2x/week. |

### REG-Vault

- **URL:** `reg.vault.rip`
- **Coverage:** 91,193 games across 99 systems.
- **Media:** box art, screenshots, videos.
- **Languages:** multilingual metadata.
- **API:** REST + MCP (Model Context Protocol) server for AI integration.
- **Auth:** public API, no key required.

### Nostalgia Lab

- **URL:** `nostalgia-lab.com`
- **Coverage:** 45 platforms.
- **API:** GraphQL.
- **Auth:** free API key required.
- **Downloads:** SQLite databases available per platform (no API needed if you download the DB).
- **Notes:** good for offline-first scraping.

### LaunchBox Games DB

- **URL:** `launchbox-app.com`
- **Format:** downloadable XML database.
- **Matching:** by exact filename match.
- **Coverage:** extensive, includes metadata, images, videos.
- **Notes:** used by the LaunchBox and BigBox frontends. The XML DB can be downloaded and used offline.

### Playmatch

- **URL:** `playmatch.com`
- **Type:** hash-based matching service.
- **Auth:** none.
- **Notes:** open source, community-driven. Proxies data from IGDB, ScreenScraper, and other sources. Good for identifying ROMs by hash without needing multiple API keys.

### SteamGridDB

- **URL:** `www.steamgriddb.com`
- **API:** REST, API key required.
- **Media:** custom cover art, logos, icons, hero images (primarily for Steam but usable for any game).
- **Notes:** no game metadata — purely an asset repository. Community-uploaded assets. Good for custom frontend themes.

## DAT File Repositories

DAT files are XML files (Logiqx format) that contain CRC32/SHA1/MD5 hashes for known good ROM dumps. They are used to verify ROM integrity and identify ROMs by hash.

| Source | Coverage | Format | Update Frequency | URL |
|--------|----------|--------|-----------------|-----|
| **No-Intro** | Cartridge ROMs | XML DAT (Logiqx) | Daily | `datomatic.no-intro.org` |
| **Redump** | Optical disc media | XML DAT (Logiqx) | Daily | `redump.org` |
| **TOSEC** | Microcomputers + all | XML DAT | ~2x/year | `tosec.org` |
| **libretro-database** | Mix No-Intro/Redump | `.rdb` (SQLite) | Maintained | `github.com/libretro/libretro-database` |
| **Retool** | 1G1R filters | Clone lists + metadata | Hand-maintained | `github.com/unexpectedpanda/retool` |

### No-Intro

- **Coverage:** cartridge-based ROMs (console, handheld, arcade).
- **Format:** XML DAT files in Logiqx format.
- **Update:** daily via `datomatic.no-intro.org`.
- **Use:** verify ROM integrity, identify ROMs by exact hash match. The gold standard for cartridge ROMs.

### Redump

- **Coverage:** optical disc media (CD, DVD, Blu-ray, GD-ROM).
- **Format:** XML DAT files in Logiqx format.
- **Update:** daily via `redump.org`.
- **Use:** verify disc images. The gold standard for disc-based games.

### TOSEC (The Old School Emulation Center)

- **Coverage:** microcomputers, home computers, and everything else not covered by No-Intro/Redump.
- **Scale:** ~4,245 DAT files, 1M+ sets.
- **Update:** ~2x/year.
- **Use:** comprehensive coverage of older systems. Less strict than No-Intro (includes alternate dumps, hacks, etc.).

### libretro-database

- **Coverage:** curated mix of No-Intro and Redump sets.
- **Format:** `.rdb` files (SQLite databases).
- **URL:** `github.com/libretro/libretro-database`.
- **Use:** used by RetroArch for internal ROM identification.

### Retool

- **Coverage:** 1G1R (1 Game 1 ROM) filters and clone lists.
- **Format:** clone list JSON files + filtered DATs.
- **URL:** `github.com/unexpectedpanda/retool`.
- **Use:** reduces redundant ROMs (same game across regions) to a single representative. Hand-maintained clone lists.

## Asset Repositories

Downloadable media (box art, screenshots, logos) for offline or low-bandwidth scraping.

| Source | Assets | Auth | Notes |
|--------|--------|------|-------|
| **libretro-thumbnails** (GitHub) | Box arts, screenshots, titles, logos | none | 130+ system repos. CDN at `thumbnails.libretro.com`. ~879 stars. |
| **OpenVGDB** (GitHub releases) | SQLite DB + cover URLs | none | v29.0+. ~70 stars. Downloadable. |
| **NostalgiaDB** | Per-platform SQLite downloads | free login | 45 platforms. |
| **TheGamesDB CDN** | Boxart, Fanart, Screenshots, Banners, Clearlogos | API key | `cdn.thegamesdb.net` |
| **REG-Vault CDN** | Box art, screenshots, videos | none | Served through REG-Vault API. |
| **SteamGridDB** | Custom covers, logos, icons | API key | Community-uploaded. |

### libretro-thumbnails

- **URL:** `github.com/libretro-thumbnails` (130+ per-system repos).
- **CDN:** `thumbnails.libretro.com`.
- **Folders:** `Named_Snaps`, `Named_Boxarts`, `Named_Titles`.
- **Format:** PNG files named after the game (spaces replaced with underscores).
- **Notes:** no API needed. Clone the repos or use the CDN. Coverage varies by system.

### OpenVGDB

- **URL:** `github.com/OpenVGDB/OpenVGDB` releases.
- **Format:** SQLite database with cover URLs.
- **Version:** v29.0+.
- **Notes:** can be downloaded and used offline. The `openvgdb` provider in multiscraper scrapes the web version, but the SQLite DB is a better option for offline use.

## Rate Limiting & Blocking Detection

### Block detection (`block_detect.py`)

The `detect_blocked()` function checks for:

1. HTTP status codes 403, 503, 429.
2. Response headers containing `cf-ray` or `cf-mitigated` (Cloudflare).
3. Body containing keywords: `cloudflare`, `cf-ray`, `cf_chl_opt`, `captcha`, `challenge`, `just a moment`, `checking your browser`, `are you human`, `ddg_captcha`.

If any match, the provider is marked as blocked and placed in a cooldown for `cooldown_after_blocked_sec` (default 1800 seconds / 30 minutes).

### Token-bucket rate limiter

Each provider has a `rate_limit_per_sec` class variable. The cascade enforces this with a token-bucket limiter:

- `burst` (default 1): allowed burst above the rate.
- The bucket blocks the worker until a token is available, preventing bursts from reaching the upstream.
- `max_consecutive_failures` (default 3): after this many consecutive failures, the provider is blocked.

### Provider-specific rate limits

| Provider | `rate_limit_per_sec` | Notes |
|----------|---------------------|-------|
| `local_override` | 1000.0 | effectively unlimited |
| `screenscraper` | 2.0 | authenticated |
| `igdb` | 4.0 | Twitch OAuth2 |
| `mobygames` | 1.0 | paid |
| `giantbomb` | 0.05 | 200/hour |
| `retroachievements` | 1.0 | |
| `rawg` | 5.0 | generous |
| `thegamesdb` | 1.0 | |
| `libretro_thumbnails` | 0.5 | file probes |
| `openvgdb` | 1.0 | HTML scraping |
| `gamefaqs` | 0.5 | HTML scraping, Cloudflare |

## Configuration Recommendations

### 1. Full online (best coverage)

Enable ScreenScraper (retro) + IGDB (modern) + RAWG (backup modern). Disable the rest.

```yaml
providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SCREENSCRAPER_DEV_ID}
      devpassword: ${env:SCREENSCRAPER_DEV_PASSWORD}
  - id: hasheous
    priority: 7
    enabled: true
  - id: igdb
    priority: 10
    enabled: true
    config:
      client_id: ${env:TWITCH_CLIENT_ID}
      client_secret: ${env:TWITCH_CLIENT_SECRET}
  - id: rawg
    priority: 30
    enabled: true
    config:
      api_key: ${env:RAWG_API_KEY}
  - id: local_fallback
    priority: 9999
    enabled: true
```

### 2. API-key free

No API keys needed. Uses Hasheous (hash identification) + libretro_thumbnails + OpenVGDB + GameFAQs.

```yaml
providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: hasheous
    priority: 7
    enabled: true
  - id: screenscraper
    priority: 5
    enabled: true   # works without devid/devpassword at lower rate
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
```

### 3. Offline-first

Local overrides + OpenVGDB SQLite + libretro-thumbnails local mirror. No network calls.

```yaml
providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: libretro_thumbnails
    priority: 40
    enabled: true
  - id: local_fallback
    priority: 9999
    enabled: true
```

### 4. High-volume scraping

Maximize throughput with high-quota providers.

```yaml
providers:
  - id: local_override
    priority: 1
    enabled: true
  - id: rawg
    priority: 30
    enabled: true
    config:
      api_key: ${env:RAWG_API_KEY}
  - id: igdb
    priority: 10
    enabled: true
    config:
      client_id: ${env:TWITCH_CLIENT_ID}
      client_secret: ${env:TWITCH_CLIENT_SECRET}
  - id: giantbomb
    priority: 20
    enabled: true
    config:
      api_key: ${env:GIANTBOMB_API_KEY}
  - id: local_fallback
    priority: 9999
    enabled: true
```

## Match Scoring

The `compute_match_score()` function in `match.py` normalizes names (lowercase, strip articles like "the"/"a"/"an", collapse spaces) and compares:

- **Exact match** (after normalization): score 1.0
- **Substring match** (rom in candidate or vice versa): max(0.75, length_ratio)
- **Fuzzy match**: `difflib.SequenceMatcher.ratio()` — character-level similarity

The cascade stops when a candidate's score reaches `match_threshold` (default 0.7).

## References

### Project source files

- `src/multiscraper/providers/base.py` — Provider and Identifier Protocols
- `src/multiscraper/providers/cascade.py` — cascade orchestration
- `src/multiscraper/providers/block_detect.py` — block detection
- `src/multiscraper/providers/match.py` — match scoring
- `src/multiscraper/providers/registry.py` — provider auto-discovery
- `src/multiscraper/providers/local.py` — local override/fallback
- `src/multiscraper/providers/hasheous.py` — Hasheous identifier
- `src/multiscraper/providers/screenscraper.py` — ScreenScraper
- `src/multiscraper/providers/igdb.py` — IGDB
- `src/multiscraper/providers/mobygames.py` — MobyGames
- `src/multiscraper/providers/giantbomb.py` — GiantBomb
- `src/multiscraper/providers/retroachievements.py` — RetroAchievements
- `src/multiscraper/providers/rawg.py` — RAWG
- `src/multiscraper/providers/thegamesdb.py` — TheGamesDB
- `src/multiscraper/providers/libretro_thumbnails.py` — LibRetro Thumbnails
- `src/multiscraper/providers/openvgdb.py` — OpenVGDB
- `src/multiscraper/providers/gamefaqs.py` — GameFAQs
- `src/multiscraper/models.py` — MediaType, Candidate, Rom models
- `config/sources.yaml` — provider configuration

### Upstream API documentation

- ScreenScraper: [screenscraper.fr/api.php](https://www.screenscraper.fr/api.php)
- IGDB: [api-docs.igdb.com](https://api-docs.igdb.com/)
- MobyGames: [mobygames.com/info/api](https://www.mobygames.com/info/api/)
- GiantBomb: [giantbomb.com/api](https://www.giantbomb.com/api/)
- RetroAchievements: [api-docs.retroachievements.org](https://api-docs.retroachievements.org/)
- RAWG: [api.rawg.io/docs](https://api.rawg.io/docs/)
- TheGamesDB: [thegamesdb.net](https://thegamesdb.net/)
- Hasheous: [hasheous.org](https://hasheous.org/)
- LibRetro Thumbnails: [github.com/libretro-thumbnails](https://github.com/libretro-thumbnails)
- OpenVGDB: [vgdb.io](https://vgdb.io/)

### Alternative sources

- REG-Vault: [reg.vault.rip](https://reg.vault.rip/)
- Nostalgia Lab: [nostalgia-lab.com](https://nostalgia-lab.com/)
- LaunchBox: [launchbox-app.com](https://www.launchbox-app.com/)
- Playmatch: [playmatch.com](https://playmatch.com/)
- SteamGridDB: [www.steamgriddb.com](https://www.steamgriddb.com/)
- No-Intro: [datomatic.no-intro.org](https://datomatic.no-intro.org/)
- Redump: [redump.org](https://redump.org/)
- TOSEC: [tosec.org](https://www.tosec.org/)
- libretro-database: [github.com/libretro/libretro-database](https://github.com/libretro/libretro-database)
- Retool: [github.com/unexpectedpanda/retool](https://github.com/unexpectedpanda/retool)

### Internal docs

- `docs/research/screenscraper-api.md` — detailed ScreenScraper API research
- `docs/research/alternatives.md` — provider comparison research
- `docs/research/emulationstation.md` — EmulationStation format notes
- `docs/architecture.md` — system architecture
- `docs/configuration.md` — configuration guide
- `docs/adding-a-provider.md` — how to add a new provider
