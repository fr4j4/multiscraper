# Provider Alternatives — Research Notes

`multiscraper` ships with 13 provider entries: 11 distinct media
sources, 1 identifier source (`hasheous`), and the local provider
in two roles (`local_override` and `local_fallback`). This
document compares them on auth, media coverage, and rate limit,
so the user can decide which to enable in `sources.yaml`.

The "Cascade priority" column is the default in
`config/sources.example.yaml`. Lower runs first; the first
provider that returns a candidate above `match_threshold` (0.7)
wins.

| # | Provider | Type | Auth | Media | Rate (per sec) | Cascade priority |
|---|---|---|---|---|---|---|
| 1 | `local_override` | media, offline | none | all 10 | N/A | 1 |
| 2 | `hasheous` | identifier | none | N/A | 2 | n/a |
| 3 | `screenscraper` | media | devid/devpassword (optional) | all 10 | 2 | 5 |
| 4 | `igdb` | media | Twitch OAuth2 | image, thumb, video | 4 | 10 |
| 5 | `mobygames` | media | api_key | image, thumb, screenshot | 1 | 15 |
| 6 | `giantbomb` | media | api_key | image, video | 0.05 (200/h) | 20 |
| 7 | `retroachievements` | media | api_key + username | image, logo | 1 | 25 |
| 8 | `rawg` | media | api_key | image, thumb, background | 5 | 30 |
| 9 | `thegamesdb` | media | api_key v2 | image, fanart, screenshot, banner, logo | 1 | 35 |
| 10 | `libretro_thumbnails` | media, offline | none | image, marquee, box3d, manual, logo | 0.5 | 40 |
| 11 | `openvgdb` | media | none | image, screenshot | 1 | 45 |
| 12 | `gamefaqs` | media | none | screenshot, desc | 0.5 | 50 |
| 13 | `local_fallback` | media, offline | none | all 10 | N/A | 9999 |

## Per-provider notes

### `local_override` (priority 1)

- **Type:** offline, no network.
- **Source:** SQLite `source_overrides` table (managed by
  `multiscraper override ...`).
- **Auth:** none.
- **Media:** any type the user uploaded. Acts as a curated
  override: if the user hand-fixed the metadata for a specific
  ROM, this provider returns it before any network call.
- **Behavior:** returns at most one `Candidate` with
  `match_score=1.0`. The cascade stops on it immediately.

### `hasheous` (identifier-only)

- **Type:** identifier, not a media provider.
- **Source:** `https://hasheous.org/api/v1/hasheous/lookup/<hash>`.
- **Auth:** none.
- **Used:** only when the media cascade failed to find a match.
  The result is a canonical name that the cascade re-uses to
  re-query other providers.
- **Notes:** implemented in `providers/hasheous.py`. Uses
  `sha1` if available, otherwise `crc32`.

### `screenscraper` (priority 5)

- **Type:** media.
- **Auth:** optional `devid` + `devpassword`. Lifts the daily
  quota from ~5000 to ~50,000 calls.
- **Media:** all 10 types.
- **Rate:** 2 req/s authenticated, 1 req/s unauthenticated.
- **Strengths:** the most complete retro database. Best metadata
  for NES, SNES, Genesis, arcade, and most pre-2010 platforms.
  Multilingual text (`en`, `fr`, `es`, `de`, `it`, `pt`, `jp`).
- **Weaknesses:** aggressive rate limiting; Cloudflare challenge
  page if you exceed limits. Cold start (no credentials) gets
  blocked easily.
- **See also:** `docs/research/screenscraper-api.md`.

### `igdb` (priority 10)

- **Type:** media.
- **Auth:** Twitch OAuth2 (`client_id` + `client_secret`).
- **Media:** `image`, `thumbnail`, `video`.
- **Rate:** 4 req/s.
- **Strengths:** the best database for modern and indie games.
  Twitch login is free.
- **Weaknesses:** modern games only. Localised metadata is
  English-only. Slow token refresh on cold start.

### `mobygames` (priority 15)

- **Type:** media.
- **Auth:** `api_key` (request from
  [mobygames.com/info/api](https://www.mobygames.com/info/api/)).
- **Media:** `image`, `thumbnail`, `screenshot`.
- **Rate:** 1 req/s.
- **Strengths:** highest-quality metadata for commercial games,
  with credits and release info. Good for 1970s–2000s.
- **Weaknesses:** only ~30% of games have cover art. Slow.

### `giantbomb` (priority 20)

- **Type:** media.
- **Auth:** `api_key` (request from
  [giantbomb.com/api](https://www.giantbomb.com/api/)).
- **Media:** `image`, `video`.
- **Rate:** 0.05 req/s (200/h). The strictest of the bunch.
- **Strengths:** real gameplay videos for many titles. Good wiki
  metadata.
- **Weaknesses:** the 200/hour cap makes it a "background"
  provider. Skip it for large runs.

### `retroachievements` (priority 25)

- **Type:** media.
- **Auth:** `username` + `api_key` (web API key, not a console
  token).
- **Media:** `image`, `logo`.
- **Rate:** 1 req/s.
- **Strengths:** unmatched for classic 8/16-bit era. Tied to
  RetroAchievements' achievement set data; if a game has
  achievements, the metadata is curated.
- **Weaknesses:** coverage drops off after PS1/N64. No video.

### `rawg` (priority 30)

- **Type:** media.
- **Auth:** `api_key` (request from
  [rawg.io](https://rawg.io/apidocs)).
- **Media:** `image`, `thumbnail`, `background`.
- **Rate:** 5 req/s (generous).
- **Strengths:** 500,000+ games. Modern and indie coverage is
  excellent. Highest throughput of the API providers.
- **Weaknesses:** weak retro coverage. English-only text.

### `thegamesdb` (priority 35)

- **Type:** media.
- **Auth:** `api_key` (v2, request from
  [thegamesdb.net](https://thegamesdb.net/)).
- **Media:** `image`, `fanart`, `screenshot`, `banner`, `logo`.
- **Rate:** 1 req/s.
- **Strengths:** same community as the legacy v1, with a
  redesigned API. The only provider with `banner` art. Good
  fanart.
- **Weaknesses:** v2 is still marked experimental by upstream;
  field names changed without notice in past releases.

### `libretro_thumbnails` (priority 40)

- **Type:** media, offline (no API).
- **Source:** probes the
  [libretro-thumbnails](https://github.com/libretro-thumbnails)
  GitHub repo by name.
- **Auth:** none.
- **Media:** `image`, `marquee`, `box3d`, `manual`, `logo`.
- **Rate:** 0.5 req/s (file download, not API call).
- **Strengths:** very stable, no auth, no rate limit. High
  quality art for the systems that libretro supports.
- **Weaknesses:** name match is required (no hash). Coverage is
  uneven — some systems are great, others are nearly empty.

### `openvgdb` (priority 45)

- **Type:** media.
- **Source:** HTML scraping at [vgdb.io](https://vgdb.io/).
- **Auth:** none.
- **Media:** `image`, `screenshot`.
- **Rate:** 1 req/s.
- **Strengths:** another fallback for hashes. No auth needed.
- **Weaknesses:** HTML scraping is fragile; the upstream does
  not publish an API.

### `gamefaqs` (priority 50)

- **Type:** media.
- **Source:** HTML scraping of [gamefaqs.gamespot.com](https://gamefaqs.gamespot.com/).
- **Auth:** none.
- **Media:** `screenshot`, `desc`.
- **Rate:** 0.5 req/s.
- **Strengths:** last-resort source of long-form descriptions.
  Large catalog.
- **Weaknesses:** Cloudflare challenge is common. The
  `are-you-human` redirect is detected by
  `block_detect.detect_blocked` and triggers a 30-minute
  cooldown. No images.

### `local_fallback` (priority 9999)

- **Type:** offline, no network.
- **Source:** same `source_overrides` table as `local_override`.
- **Auth:** none.
- **Media:** all 10 (whatever the user uploaded).
- **Behavior:** runs **after** every other provider. If the
  cascade produced no candidate above `match_threshold`, this
  provider scans the override table and returns the best match
  by `confidence` (default 1.0 if no confidence is set).

## Choosing a cascade

The defaults in `sources.example.yaml` reflect a typical
home-user tradeoff: ScreenScraper first, modern providers next,
fallbacks at the bottom. To tune:

- **Local-only.** Disable every provider with `enabled: false`
  except `local_override`, `local_fallback`, and `libretro_thumbnails`.
  This avoids any API keys but the metadata will be thin.
- **Headless server with API quotas.** Disable `giantbomb` and
  `rawg`, keep the rest. Doubles effective daily quota.
- **Modern-only collection.** Move `igdb` and `rawg` above
  `screenscraper`; disable everything that targets retro
  platforms.
- **Strict matching.** Raise `match_threshold` to `0.85` and
  drop `gamefaqs` (it tends to return false positives).
- **Loose matching.** Lower `match_threshold` to `0.5`; add
  `hasheous` results into the cascade by enabling its
  identifier-style use (default).

## Upstream references

- IGDB: [api-docs.igdb.com](https://api-docs.igdb.com/)
- RAWG: [api.rawg.io/docs](https://api.rawg.io/docs/)
- MobyGames: [mobygames.com/info/api](https://www.mobygames.com/info/api/)
- GiantBomb: [giantbomb.com/api](https://www.giantbomb.com/api/)
- RetroAchievements: [api-docs.retroachievements.org](https://api-docs.retroachievements.org/)
- TheGamesDB: [thegamesdb.net](https://thegamesdb.net/)
- LibRetro Thumbnails: [github.com/libretro-thumbnails](https://github.com/libretro-thumbnails)
- OpenVGDB: [vgdb.io](https://vgdb.io/)
- Hasheous: [hasheous.org](https://hasheous.org/)
- ScreenScraper: [screenscraper.fr/api.php](https://www.screenscraper.fr/api.php)
