# ScreenScraper API — Research Notes

[ScreenScraper.fr](https://www.screenscraper.fr/) is a community
metadata database for retro games. It is the primary provider for
`multiscraper` (priority 5 in the default cascade) and the only
one that covers all 10 `MediaType` values. This document
summarises the API v2 contract as far as `multiscraper` uses it.

## Endpoints

Base URL: `https://www.screenscraper.fr/api2`

`multiscraper` (`src/multiscraper/providers/screenscraper.py`)
hits:

- `GET /jeuInfos.php` — main metadata + media lookup.
- `GET /systemesListe.php` — system/platform catalogue (not used
  at runtime, but referenced in development).

The full list of endpoints is in the API documentation linked at
the bottom of this document. Not all endpoints are exposed to
`multiscraper`; only the ones needed for ROM matching and media
download.

## Authentication

The API does not require auth for low-volume usage but enforces a
hard daily quota. Registering a `devid` + `devpassword` lifts the
quota. `multiscraper` reads them from the provider's `config`
block in `sources.yaml`:

```yaml
providers:
  - id: screenscraper
    priority: 5
    enabled: true
    config:
      devid: ${env:SCREENSCRAPER_DEV_ID}
      devpassword: ${env:SCREENSCRAPER_DEV_PASSWORD}
      region_priority: [wor, us, eu, jp]
      language_priority: [en, es, fr]
```

To register, create a forum account at
[screenscraper.fr](https://www.screenscraper.fr/) and request API
credentials from your profile page.

`multiscraper` does not fail when the credentials are missing;
`requires_auth` is `False`. The provider is simply rate-limited
more aggressively.

## Query parameters for `jeuInfos.php`

| Param | Type | Notes |
|---|---|---|
| `devid` | str | Optional but recommended. |
| `devpassword` | str | Optional but recommended. |
| `softname` | str | Always set to `multiscraper` to identify the client. |
| `ssid` | str | Reserved; `multiscraper` does not use user accounts. |
| `sspassword` | str | Reserved. |
| `crc` | str | 32-bit CRC32 of the file, hex without `0x`. |
| `sha1` | str | 40-char SHA1 of the file, hex. |
| `romname` | str | File name including extension. Used as fallback. |
| `romtaille` | int | File size in bytes. |
| `systemeid` | int | ScreenScraper platform id (e.g. 4 for SNES). |
| `romtype` | str | `rom`, `iso`, or `disc`. |
| `media` | str | Comma-separated list of `MediaType` tokens (`mixrbv1`, `box-3D`, ...). Optional. |
| `region` | str | Region priority override. |
| `langue` | str | Language priority override. |

`multiscraper` always sends `crc` and `sha1` (when both are known)
plus the platform id from its `platform_map`. When neither hash is
available it falls back to `romname` (name-based search).

## Response

The response is XML. Top-level element is `<Data>`; the payload
is either a `<jeu>` block or an `<erreur>` block.

### Success

```xml
<Data>
  <jeu>
    <id>12345</id>
    <noms>
      <nom region="wor" lang="en">Super Mario World</nom>
      <nom region="us" lang="en">Super Mario World</nom>
    </noms>
    <synopsis>
      <synopsis lang="en">...</synopsis>
    </synopsis>
    <dates>
      <date region="wor">1990-11-23</date>
    </dates>
    <developpeur>Nintendo</developpeur>
    <editeur>Nintendo</editeur>
    <genres>
      <genre lang="en">Platform</genre>
    </genres>
    <joueurs>1</joueurs>
    <note>0.95</note>
    <medias>
      <media type="box2D" url="https://..." format="jpg"/>
      <media type="ss" url="https://..." format="jpg"/>
      <media type="video" url="https://..." format="mp4"/>
      <media type="screenmarquee" url="https://..." format="png"/>
      <media type="box-3D" url="https://..." format="png"/>
      <media type="box2D-back" url="https://..." format="jpg"/>
      <media type="fanart" url="https://..." format="jpg"/>
      <media type="manuel" url="https://..." format="pdf"/>
      <media type="mixrbv1" url="https://..." format="png"/>
      <media type="logo" url="https://..." format="png"/>
    </medias>
  </jeu>
</Data>
```

### Error / blocked

```xml
<Data>
  <erreur>
    <code>429</code>
    <description>Too many requests, please slow down.</description>
  </erreur>
</Data>
```

ScreenScraper-specific blocking signals (used by
`detect_blocked`):

- HTTP 403/503/429 with `<erreur>` containing rate-limit codes.
- HTTP 200 with an empty or malformed `<Data>` body.

The provider translates these into `BlockedError` so the cascade
can mark the provider as blocked for
`cooldown_after_blocked_sec` (default 30 min).

## Media type mapping

| ScreenScraper `media type=` | `multiscraper` `MediaType` |
|---|---|
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

The mapping is in `providers/screenscraper.py` (`_SS_MEDIA_MAP`).
The reverse mapping (used by `gamelist_xml.py` for the XML tag
name) is in `output/gamelist_xml.py` (`_MEDIA_TAG_MAP`).

## Region and language fallback

`multiscraper` lets the user configure both:

- `region_priority: [wor, us, eu, jp]` — order in which
  ScreenScraper regions are consulted for the `<nom>` and other
  regional fields.
- `language_priority: [en, es, fr]` — order of `<synopsis>`
  languages. If no matching language is found, `multiscraper` falls
  back to the first non-empty value (spec decisión #31,
  `fallback_strategy: best_effort`).

The provider code walks each list in order and stops on the first
non-empty hit.

## Platform map

ScreenScraper uses numeric platform ids. The provider's
`platform_map` translates the multiscraper system name to the
numeric id (e.g. `"snes": 4`). The full map is in
`providers/screenscraper.py` (`_PLATFORM_MAP`).

If the user's system is not in the map, the provider cannot
narrow the search and falls back to a name-only query.

## Rate limits

The community rate limit is undocumented precisely but the
following rules of thumb hold:

- Unauthenticated: 1 request / second, soft cap.
- Authenticated: 2 requests / second, higher daily quota.
- Burst: avoid 5+ requests in 2 seconds.

`multiscraper` configures a token-bucket rate limiter per
provider with `rate_limit_per_sec: 2.0` (default in
`provider_defaults`). The bucket blocks the worker until a token
is available, so the provider never sees a burst.

## References

- [ScreenScraper API page](https://www.screenscraper.fr/api.php)
  — official API documentation, in French.
- [ScreenScraper.cpp in RetroPie](https://github.com/RetroPie/EmulationStation/blob/master/es-app/src/scrapers/ScreenScraper.cpp)
  — a different implementation of the same calls; useful for
  field-name cross-checking.
- [Skraper](https://www.skraper.net/) — community Windows
  scraper built on the same API. Useful as a UI to validate
  matches.
