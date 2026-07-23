# multiscraper — Design Document

**Fecha:** 2026-07-22
**Estado:** Borrador para revisión
**Autor:** brainstorming colaborativo con el usuario

## Resumen ejecutivo

`multiscraper` es un scraper paralelo, multi-fuente y extensible para frontends de emulación tipo EmulationStation (RetroPie, Batocera, Recalbox, etc.). Descubre ROMs desde una carpeta local o desde una máquina remota por SSH, consulta múltiples proveedores de metadata (ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb, RetroAchievements, TheGamesDB, LibRetro Thumbnails, OpenVGDB, GameFAQs, Hasheous, override local), hace fallback en cascada si uno falla, descarga media (cover, marquee, video, box 3D, backcover, fanart, manual, miximage, logo), genera `gamelist.xml` por sistema compatible con EmulationStation, y deja un CSV detallado por cada ejecución. La orquestación es con `asyncio + aiohttp` (I/O-bound), con un supervisor que recupera workers muertos, persistencia en SQLite (WAL) y checkpoint para reanudar runs interrumpidos por SIGTERM. Está cableado un hook para `TextGenerator` OpenAI-compatible (inactivo en v1) para una futura v2 que use LLM para mejorar descripciones.

## Tabla consolidada de decisiones

| # | Decisión | Valor | Ronda |
|---|---|---|---|
| 1 | Nombre del proyecto | `multiscraper` (paquete y CLI) | ronda 1 |
| 2 | Modelo de paralelismo | `asyncio + aiohttp` | ronda 1 |
| 3 | Fuentes de datos | 13 entries (11 media + 1 identifier + 1 local con doble rol override/fallback) | ronda 2 |
| 4 | Configuración de entrada | Acepta `es_systems.cfg` y/o YAML propio | ronda 1 |
| 5 | Output | JSON propio (cache) + conversor a estructura ES | ronda 1 |
| 6 | Cache local | Sí, persistente, en SQLite | ronda 2 |
| 7 | Comportamiento si ROM ya está | Sincronizar con `gamelist.xml` existente | ronda 1 |
| 8 | LLM hook | Interfaz abstracta `TextGenerator` + `NoOpTextGenerator` default | ronda 1 |
| 9 | Cloudflare / captcha | Detección por HTTP status + HTML; fallback a otra fuente | ronda 1 |
| 10 | Granularidad CSV | 1 fila por ROM con columnas por media type | ronda 1 |
| 11 | Resiliencia de workers | Supervisor que recupera tareas muertas | ronda 1 |
| 12 | Cliente SSH | `asyncssh` (async nativo) | ronda 2 |
| 13 | Hash por defecto | `crc32` con fallback automático a `sha1` | ronda 2 |
| 14 | Cache backend | SQLite desde el inicio (WAL) | ronda 2 |
| 15 | `known_hosts` SSH | Estricto por default, flag `--auto-trust` para LANs | ronda 2 |
| 16 | Reanudación tras SIGTERM | Sí, en v1 (jobs `in_progress` → `pending` al reanudar) | ronda 2 |
| 17 | `local_override` y `local_fallback` | Modo C híbrido (override prioridad 1, fallback último) | ronda 4 |
| 18 | Columna `identify_method` | Silencioso (solo CSV), valores: `crc32`, `sha1`, `name_only`, `hasheous` | ronda 3 |
| 19 | Reanudar jobs `in_progress` | Desde cero (sin estado parcial) | ronda 3 |
| 20 | Licencia | MIT | ronda 3 |
| 21 | Idioma de docs | Inglés | ronda 3 |
| 22 | Logging | stdlib `logging` + handler `rich` a terminal + JSONL a archivo | ronda 3 |
| 23 | Verbosity de librerías | Silenciadas (WARNING) por default; `-vv` las sube a INFO | ronda 3 |
| 24 | Media root | `$HOME/multiscraper_data/media/` (configurable, no oculto) | ronda 3 |
| 25 | Default `--shutdown-timeout` | 180 segundos (3 min) | ronda 3 |
| 26 | Nomenclatura flag shutdown | `--shutdown-timeout N` | ronda 3 |
| 27 | Status para cancelado por shutdown | `TIMED_OUT` (distinto de `ERROR`) | ronda 3 |
| 28 | `match_threshold` default | 0.7 (configurable) | ronda 4 |
| 29 | Cooldown por provider tras bloqueo | 30 min default (configurable) | ronda 4 |
| 30 | `max_candidates_per_provider` | 10 default (configurable) | ronda 4 |
| 31 | Idioma de textos | `text_priority` y `name_priority` con fallback; `best_effort` default | ronda 5 |

---

## Sección 1 — Arquitectura general

### Diagrama de alto nivel

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (click)                             │
│  --roms-root | --es-systems | --config | --workers N             │
│  --batch-size | --priority-config | --force-rescrape            │
└───────────────┬──────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Orchestrator (asyncio)                          │
│  - Carga config (es_systems.cfg + YAML override)                │
│  - Crea RunContext (run_id, csv_path, logs)                     │
│  - Construye cola de Jobs: 1 Job = 1 ROM + sistema + lote       │
│  - Spawnea N workers (asyncio tasks)                            │
│  - Supervisa workers, recupera tareas muertas                   │
│  - Empuja resultados al CSV writer en streaming                  │
└────┬─────────────────────┬──────────────────────┬────────────────┘
     │                     │                      │
     ▼                     ▼                      ▼
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Config &    │    │ Job Queue        │    │ CSV Writer      │
│ Cache layer │    │ (asyncio.Queue)  │    │ (stream, lock)  │
│ - sources   │    │ partition by sys  │    │                 │
│ - cache.db  │    │ batches de B      │    │                 │
│ - gamelist  │    └──────────────────┘    └─────────────────┘
└─────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────┐
│              Worker (asyncio task) — N en paralelo               │
│  1. Toma Job de la cola                                         │
│  2. Chequea cache (SQLite) — si hit, salta                       │
│  3. Itera providers en orden de prioridad                         │
│     a. search(rom) → candidates                                 │
│     b. select_best(candidates, language) → chosen                │
│     c. fetch_media(chosen, wanted_types)                         │
│  4. Empaqueta Result                                              │
│  5. Devuelve a Orchestrator                                       │
└────┬─────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────┐
│              Source Providers (plugins tipados)                  │
│  ScreenScraper, IGDB, RAWG, MobyGames, GiantBomb,               │
│  RetroAchievements, TheGamesDB, LibRetro Thumbnails,            │
│  OpenVGDB, GameFAQs, Hasheous, local_override, local_fallback   │
│  Cada uno implementa Provider Protocol:                          │
│    name, requires_auth, async search, async fetch_media,        │
│    platform_map, detect_blocked(response)                        │
└──────────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────┐
│             Output stage                                         │
│  - .cache/multiscraper.db (SQLite con WAL)                       │
│  - $HOME/multiscraper_data/media/<system>/<rom>-<type>.<ext>    │
│  - gamelists/<system>/gamelist.xml  (conversor)                 │
│  - reports/<run_id>/run.csv                                     │
│  - reports/<run_id>/run.log.jsonl                               │
│  - reports/<run_id>/summary.json                                │
└──────────────────────────────────────────────────────────────────┘
```

### Principios

- **Asyncio + aiohttp** como motor concurrente. Cada worker = 1 `asyncio.Task`. Concurrencia efectiva = `workers × (concurrencia interna por worker para media)`.
- **Pipeline asíncrono en streaming**: el CSV se escribe fila por fila a medida que los workers terminan, no al final.
- **Recuperación ante fallos**: el `Supervisor` registra la excepción, reencola el Job (con backoff) y sigue.
- **Source providers como plugins** tipados vía `Protocol`. El usuario agrega uno creando un módulo que satisface la interfaz y registrando la ruta en YAML, o instalando un paquete externo con entry points.

### Estructura de directorios

```
multiscraper/
├── pyproject.toml
├── README.md
├── LICENSE                                 # MIT
├── CHANGELOG.md
├── config/
│   ├── sources.example.yaml
│   └── systems.example.yaml
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   ├── cli.md
│   ├── adding-a-provider.md
│   ├── ssh-setup.md
│   ├── ems_files.md
│   ├── logging.md
│   ├── research/
│   │   ├── emulationstation.md
│   │   ├── screenscraper-api.md
│   │   └── alternatives.md
│   └── plans/
│       └── 2026-07-22-multiscraper-impl.md
├── src/
│   └── multiscraper/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── logging_setup.py
│       ├── config/             # parsers y validación
│       ├── core/               # orchestrator, queue, supervisor
│       ├── transport/          # local y ssh (asyncssh)
│       ├── providers/          # 12 providers
│       ├── output/             # db, csv, xml, summary, log
│       ├── llm/                # TextGenerator protocol + noop + openai_compat
│       └── utils/
└── tests/
    ├── conftest.py
    ├── cassettes/
    ├── fixtures/
    ├── unit/
    └── integration/
```

---

## Sección 2 — Modelos de datos y formatos

### 2.1 — Modelos Pydantic (núcleo)

```python
# src/multiscraper/models.py
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


# ---------- enums ----------

class MediaType(str, Enum):
    IMAGE        = "image"
    THUMBNAIL    = "thumbnail"
    VIDEO        = "video"
    MARQUEE      = "marquee"
    BOX3D        = "box3d"
    BACKCOVER    = "backcover"
    FANART       = "fanart"
    MANUAL       = "manual"
    MIXIMAGE     = "miximage"
    LOGO         = "logo"


class ScrapeStatus(str, Enum):
    OK            = "OK"
    PARTIAL       = "PARTIAL"
    NO_MATCH      = "NO_MATCH"
    BLOCKED       = "BLOCKED"
    ERROR         = "ERROR"
    TIMED_OUT     = "TIMED_OUT"
    SKIPPED       = "SKIPPED"


class IdentifyMethod(str, Enum):
    CRC32         = "crc32"
    SHA1          = "sha1"
    NAME_ONLY     = "name_only"
    HASHEOUS      = "hasheous"


# ---------- identification ----------

class RomIdentifier(BaseModel):
    rel_path: str
    size: int
    mtime: int
    crc32: str | None = None
    sha1: str | None = None
    cache_key: str


class Rom(BaseModel):
    system: str
    rom_id: RomIdentifier
    raw_name: str
    normalized_name: str
    preferred_region: str = "wor"
    preferred_language: str = "en"


# ---------- candidates & media ----------

class MediaRef(BaseModel):
    type: MediaType
    url: HttpUrl
    ext: str
    region: str | None = None
    size_bytes: int | None = None
    source: str


class Candidate(BaseModel):
    provider: str
    source_id: str
    name: str
    match_score: float = Field(ge=0.0, le=1.0)
    releasedate: datetime | None = None
    developer: str | None = None
    publisher: str | None = None
    genre: str | None = None
    players: int | None = None
    rating: float | None = None
    description: str | None = None
    media: list[MediaRef] = []


# ---------- final result ----------

class GameMetadata(BaseModel):
    name: str
    desc: str | None = None
    rating: float | None = None
    releasedate: datetime | None = None
    developer: str | None = None
    publisher: str | None = None
    genre: str | None = None
    players: int | None = None
    sortname: str | None = None


class MediaFile(BaseModel):
    type: MediaType
    local_path: str
    ext: str
    bytes: int
    sha256: str
    source: str


class ScrapedResult(BaseModel):
    rom: Rom
    status: ScrapeStatus
    identify_method: IdentifyMethod
    chosen_provider: str | None = None
    match_score: float | None = None
    metadata: GameMetadata | None = None
    media: list[MediaFile] = []
    warnings: list[str] = []
    error: str | None = None
    elapsed_ms: int = 0
    fetched_at: datetime


# ---------- run reporting ----------

class RunTotals(BaseModel):
    roms_total: int = 0
    roms_ok: int = 0
    roms_partial: int = 0
    roms_no_match: int = 0
    roms_blocked: int = 0
    roms_error: int = 0
    roms_timed_out: int = 0
    roms_skipped: int = 0
    media_files_downloaded: int = 0
    media_bytes_total: int = 0
    identify_method_counts: dict[IdentifyMethod, int] = {}
    providers_used: dict[str, int] = {}
    error_breakdown: dict[str, int] = {}
    by_status: dict[ScrapeStatus, int] = {}
    by_provider_match: dict[str, int] = {}
    avg_match_score: float = 0.0
    p50_match_score: float = 0.0
    p95_match_score: float = 0.0
    avg_elapsed_ms_per_rom: int = 0
    throughput_roms_per_min: float = 0.0
    throughput_mb_per_min: float = 0.0


class RunReport(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    config_snapshot: dict
    totals: RunTotals = RunTotals()
    status: Literal["running", "ok", "partial", "paused", "aborted", "error"] = "running"
```

### 2.2 — Schema SQLite

**Archivo**: `.cache/multiscraper.db`. **Modo**: `WAL`. **Driver**: `aiosqlite`.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL CHECK (status IN
                        ('running','ok','partial','paused','aborted','error')),
    config_json     TEXT NOT NULL,
    totals_json     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS roms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key       TEXT NOT NULL UNIQUE,
    system          TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    raw_name        TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    size            INTEGER NOT NULL,
    mtime           INTEGER NOT NULL,
    crc32           TEXT,
    sha1            TEXT,
    first_seen_run  TEXT REFERENCES runs(id) ON DELETE SET NULL,
    UNIQUE (system, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_roms_system ON roms(system);
CREATE INDEX IF NOT EXISTS idx_roms_crc32  ON roms(crc32);
CREATE INDEX IF NOT EXISTS idx_roms_sha1   ON roms(sha1);

CREATE TABLE IF NOT EXISTS scrape_results (
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    identify_method TEXT NOT NULL,
    chosen_provider TEXT,
    match_score     REAL,
    metadata_json   TEXT,
    error           TEXT,
    warnings_json   TEXT,
    elapsed_ms      INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, rom_id)
);
CREATE INDEX IF NOT EXISTS idx_results_status ON scrape_results(run_id, status);
CREATE INDEX IF NOT EXISTS idx_results_rom    ON scrape_results(rom_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS media (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    source          TEXT NOT NULL,
    ext             TEXT NOT NULL,
    local_path      TEXT NOT NULL,
    bytes           INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    url             TEXT NOT NULL,
    UNIQUE (rom_id, type)
);
CREATE INDEX IF NOT EXISTS idx_media_rom ON media(rom_id);
CREATE INDEX IF NOT EXISTS idx_media_run ON media(run_id);

CREATE TABLE IF NOT EXISTS run_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id          INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    batch_id        INTEGER NOT NULL,
    worker_id       TEXT,
    status          TEXT NOT NULL CHECK (status IN
                        ('pending','in_progress','done','failed','skipped')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    finished_at      TEXT,
    error           TEXT,
    UNIQUE (run_id, rom_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_pending ON run_jobs(run_id, status)
    WHERE status IN ('pending','in_progress');

CREATE TABLE IF NOT EXISTS provider_state (
    provider        TEXT PRIMARY KEY,
    last_call_at    TEXT,
    blocked_until   TEXT,
    last_error      TEXT,
    total_calls     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_overrides (
    cache_key        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    desc             TEXT,
    image_path       TEXT,
    metadata_json    TEXT,
    media_paths_json TEXT,
    confidence       REAL DEFAULT 1.0,
    note             TEXT,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS text_provenance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rom_id      INTEGER NOT NULL REFERENCES roms(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    language    TEXT,
    source      TEXT NOT NULL,
    UNIQUE (run_id, rom_id, field)
);
CREATE INDEX IF NOT EXISTS idx_text_prov_rom ON text_provenance(rom_id);
```

**Notas**:
- `cache_key = sha1(rel_path || size || mtime || crc32)`. Detecta cambios en la ROM sin re-hashear.
- `UNIQUE (system, rel_path)` evita duplicados lógicos.
- `UNIQUE (rom_id, type)` en `media` permite overwrite si una corrida nueva trae mejor calidad.
- Índice parcial en `run_jobs` para acelerar queries de "jobs pendientes para reanudar".
- Migraciones: tabla `schema_version` con archivos `db/migrations/0001_initial.sql`, etc., aplicados en orden.
- WAL activado con `PRAGMA journal_mode=WAL`. `PRAGMA busy_timeout=5000`.

### 2.3 — Formato CSV (`reports/<run_id>/run.csv`)

**Una fila por ROM**. CSV streaming, flush cada 50 filas, encoding UTF-8, `lineterminator="\n"`, `quoting=QUOTE_MINIMAL`.

#### Encabezado (orden exacto)

```
run_id,row_seq,system,batch_id,worker_id,rom_relpath,rom_raw_name,rom_size,
rom_crc32,rom_sha1,identify_method,status,match_score,chosen_provider,
fetched_at,elapsed_ms,error,warnings,
name,name_language,
desc,desc_language,desc_source,
genre,genre_language,genre_source,
releasedate,developer,publisher,
players,rating,
image,thumbnail,video,marquee,box3d,backcover,fanart,manual,miximage,logo,
total_media_ok,total_media_bytes
```

#### Semántica de las columnas de media

| Valor | Significado |
|---|---|
| `OK` | descargado correctamente |
| `OK:<bytes>` | descargado (formato compacto) |
| `MISSING` | el provider no devolvió este tipo |
| `SKIPPED` | tipo deshabilitado en config |
| `ERROR:<msg>` | fallo al descargar (404, timeout, etc.) |
| vacío | la ROM no llegó a la fase de media (típicamente `NO_MATCH`) |

El path local del archivo NO va en el CSV (se obtiene cruzando con SQLite si hace falta). Esto mantiene el CSV compacto y legible.

### 2.4 — Formato `gamelist.xml` (EmulationStation)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<gameList>
  <game>
    <path>./Super Mario World (USA).smc</path>
    <name>Super Mario World</name>
    <desc>...</desc>
    <rating>0.95</rating>
    <releasedate>19901123T000000</releasedate>
    <developer>Nintendo</developer>
    <publisher>Nintendo</publisher>
    <genre>Platform</genre>
    <players>1</players>
    <sortname>Super Mario World</sortname>
    <image>./downloaded_images/snes/Super Mario World-image.jpg</image>
    <thumbnail>./downloaded_images/snes/Super Mario World-thumb.jpg</thumbnail>
    <video>./downloaded_images/snes/Super Mario World-video.mp4</video>
    <marquee>./downloaded_images/snes/Super Mario World-marquee.png</marquee>
  </game>
  <game>
    <path>./Mystery Game (USA).rom</path>
  </game>
</gameList>
```

**Reglas**:
- Solo `<path>` siempre; ES rellena el resto.
- Tags omitidos si vacíos.
- `releasedate` en formato `%Y%m%dT%H%M%S`.
- Paths relativos al `<path>` del sistema (portabilidad).
- Encoding UTF-8, `xml_declaration=True`, `short_empty_elements=False`.
- Escape XML via `xml.sax.saxutils.escape`.
- Pretty print, indent 2 espacios.
- Ubicación: `gamelists/<system>/gamelist.xml`.

### 2.5 — Convención de nombres de archivo de media

**Patrón**: `<normalized_name>-<type>.<ext>`.

Reglas de normalización del filename:
1. Tomar `rom.normalized_name`.
2. Strip de caracteres no permitidos: `< > : " / \ | ? *` y control chars.
3. Secuencias de whitespace → un único `_`.
4. Trim de `_` y `.` al inicio/final.
5. **Colisiones**: sufijo `_<crc32[:6]>` antes del tipo. Ej. `Super_Mario_World_a1b2c3-image.png`.
6. **Case-insensitive FS** (Windows/macOS): `Foo-image_1.png` para el siguiente.

#### Tabla de extensiones por tipo

| `MediaType` | Sufijo | Extensiones aceptadas | Ext preferida |
|---|---|---|---|
| `image` | `-image` | `.png`, `.jpg`, `.jpeg`, `.webp` | `.jpg` |
| `thumbnail` | `-thumb` | `.png`, `.jpg` | `.jpg` |
| `video` | `-video` | `.mp4`, `.webm` | `.mp4` |
| `marquee` | `-marquee` | `.png`, `.jpg` | `.png` |
| `box3d` | `-3dbox` | `.png`, `.jpg` | `.png` |
| `backcover` | `-backcover` | `.png`, `.jpg` | `.jpg` |
| `fanart` | `-fanart` | `.png`, `.jpg` | `.jpg` |
| `manual` | `-manual` | `.pdf` | `.pdf` |
| `miximage` | `-miximage` | `.png`, `.jpg` | `.png` |
| `logo` | `-logo` | `.png` | `.png` |

#### Ubicación física

```
$HOME/multiscraper_data/media/
  <system>/
    Super_Mario_World-image.jpg
    Super_Mario_World-thumb.jpg
    Super_Mario_World-video.mp4
    Super_Mario_World-marquee.png
```

`media_root` se define en `systems.yaml` o por flag CLI `--media-root` (default: `$HOME/multiscraper_data/media/`). `local_path` en SQLite se guarda **relativo a `media_root`** para portabilidad.

### 2.6 — `summary.json` y `run.log.jsonl`

#### `summary.json`

```json
{
  "run_id": "01HXYZ...",
  "started_at": "2026-07-22T22:00:00Z",
  "finished_at": "2026-07-22T22:18:42Z",
  "duration_seconds": 1122,
  "status": "ok",
  "config_snapshot": { },
  "totals": {
    "roms_total": 3842,
    "roms_ok": 3201,
    "roms_partial": 187,
    "roms_no_match": 312,
    "roms_blocked": 0,
    "roms_error": 12,
    "roms_timed_out": 0,
    "roms_skipped": 130,
    "media_files_downloaded": 21203,
    "media_bytes_total": 6584729183,
    "identify_method_counts": {
      "crc32": 3401,
      "sha1": 28,
      "name_only": 287,
      "hasheous": 126
    },
    "providers_used": {
      "screenscraper": 3104,
      "igdb": 184,
      "mobyges": 95,
      "hasheous": 126
    }
  },
  "per_system": {
    "snes":   {"total": 1240, "ok": 1102, "partial": 42, "no_match": 88, "error": 8},
    "psx":    {"total": 856,  "ok": 712,  "partial": 23, "no_match": 109, "error": 4},
    "mame":   {"total": 1746, "ok": 1387, "partial": 122, "no_match": 215, "error": 0}
  },
  "warnings": [
    {
      "type": "low_match_rate",
      "system": "mame",
      "metric": "no_match_ratio",
      "value": 0.42,
      "threshold": 0.30,
      "suggestion": "Check that es_systems.cfg <platform> tags match the MAME romset version."
    }
  ],
  "errors_sample": [
    {"rom": "./mame/GameX.zip", "error": "screenscraper: 503 after 3 retries"},
    {"rom": "./psx/GameY.bin",  "error": "igdb: not_found"}
  ]
}
```

#### `run.log.jsonl` (evento por línea)

```json
{"ts":"2026-07-22T22:00:00.123Z","level":"INFO","event":"run_start","run_id":"01HXYZ...","systems":["snes","psx","mame"]}
{"ts":"2026-07-22T22:00:01.450Z","level":"DEBUG","event":"hash_upgraded","rom":"./snes/Suspect.crc","from":"crc32","to":"sha1","reason":"collision"}
{"ts":"2026-07-22T22:00:03.220Z","level":"INFO","event":"rom_done","rom":"./snes/Super Mario World (USA).smc","status":"OK","provider":"screenscraper","elapsed_ms":1234}
{"ts":"2026-07-22T22:00:04.110Z","level":"WARNING","event":"provider_blocked","provider":"gamefaqs","reason":"cloudflare_challenge","blocked_until":"2026-07-22T23:00:04Z"}
{"ts":"2026-07-22T22:00:05.000Z","level":"INFO","event":"provider_skipped","provider":"gamefaqs","reason":"blocked"}
{"ts":"2026-07-22T22:00:05.500Z","level":"INFO","event":"shutdown_initiated","reason":"SIGTERM","soft_drain":true,"active_workers":4,"in_download":2}
{"ts":"2026-07-22T22:01:00.000Z","level":"INFO","event":"worker_drained","worker":"W-02","phase_was":"downloading","elapsed_in_job_ms":45230,"bytes_downloaded":12000000}
{"ts":"2026-07-22T22:18:42.000Z","level":"INFO","event":"run_end","status":"ok","totals":{}}
```

Vocabulario cerrado de `event` (documentado en `docs/logging.md`):
`run_start, run_end, run_paused, run_resumed, run_aborted, rom_discovered, rom_started, rom_done, rom_failed, rom_skipped, provider_called, provider_blocked, provider_skipped, provider_unblocked, hash_upgraded, hash_failed, cache_hit, cache_miss, cache_invalidated, media_downloaded, media_failed, media_skipped, ssh_connected, ssh_disconnected, ssh_reconnected, ssh_error, worker_started, worker_died, worker_recovered, shutdown_initiated, worker_drained, worker_force_cancelled, all_providers_blocked`.

---

## Sección 3 — Orquestador, cola, workers, supervisor, batches, SIGTERM

### 3.1 — Diagrama de componentes

```
                 ┌────────────────────────────────────────────┐
                 │              CLI (main)                    │
                 │  parse args, load config, setup logging,   │
                 │  init transport, init providers, init DB,  │
                 │  → start Orchestrator                     │
                 └────────────────────┬───────────────────────┘
                                      │
                 ┌────────────────────▼───────────────────────┐
                 │           Orchestrator (asyncio)           │
                 │  - signals: SIGTERM/SIGINT → shutdown Evt  │
                 │  - run_id = new_ulid()                     │
                 │  - creates RunReport in DB                 │
                 │  - iterates systems → builds jobs           │
                 │  - splits jobs into batches                │
                 │  - spawns N WorkerTasks                    │
                 │  - spawns CSVWriterTask (consumes results) │
                 │  - spawns ProgressReporterTask             │
                 │  - on shutdown: drain → persist → exit     │
                 └────┬───────────────┬──────────────┬────────┘
                      │               │              │
            ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
            │   JobQueue     │ │ Worker     │ │ ResultQueue   │
            │ asyncio.Queue  │ │ Tasks (N)  │ │ asyncio.Queue │
            └────────────────┘ └─────┬──────┘ └───────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ Transport (Local/   │
                          │ Ssh via asyncssh)   │
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ Providers chain     │
                          │ (cascading fallback)│
                          └─────────────────────┘
```

### 3.2 — Tipos centrales

```python
# src/multiscraper/orchestrator/models.py

class JobState(str, Enum):
    PENDING      = "pending"
    IN_PROGRESS  = "in_progress"
    DONE         = "done"
    FAILED       = "failed"
    SKIPPED      = "skipped"

class WorkerPhase(str, Enum):
    IDLE          = "idle"
    LOOKING_UP    = "looking_up"
    DOWNLOADING   = "downloading"
    FINALIZING    = "finalizing"

class Job(BaseModel):
    job_id: str
    run_id: str
    rom: Rom
    batch_id: int
    system: str
    attempts: int = 0
    state: JobState = JobState.PENDING
    worker_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

class JobResult(BaseModel):
    job: Job
    result: ScrapedResult
    media_downloaded: int
    bytes_downloaded: int

class ShutdownReason(str, Enum):
    COMPLETED   = "completed"
    SIGTERM     = "sigterm"
    SIGINT      = "sigint"
    ERROR       = "error"
    USER_ABORT  = "user_abort"
```

### 3.3 — Estructura de batches

1. El orquestador recibe del transport la lista de ROMs por sistema.
2. **Filtra las que ya están en cache** (status `OK|PARTIAL` recientes o cualquier status dentro del TTL).
3. Para cada sistema, divide las restantes en **batches de tamaño B** (`--batch-size`, default `50`).
4. **Numeración**: por sistema, reinicia en 0.
5. **Encolado**: todos los jobs van al mismo `JobQueue`. No hay queue por sistema.

**Por qué batches**:
- **Trazabilidad**: `batch_id` en CSV ayuda a correlacionar errores.
- **Throttling inteligente**: si el primer job del batch detecta `provider_blocked`, las 49 restantes se salvan.
- **Reanudación**: al reanudar, los jobs van a su batch original.
- **No** se paraleliza "un batch por worker". Los workers son transversales a los batches.

### 3.4 — Worker (detalle)

```python
async def worker_task(worker_id: str, ctx: WorkerContext) -> None:
    while not ctx.shutdown.is_set():
        try:
            job = await asyncio.wait_for(ctx.queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue

        try:
            await ctx.db.mark_job_in_progress(job, worker_id)
            result = await process_rom(ctx, job)
            await ctx.result_queue.put(JobResult(job, result, ...))
            await ctx.db.mark_job_done(job)
        except Exception as e:
            logger.exception("worker_died", extra={"worker": worker_id, "job": job.job_id})
            await ctx.db.mark_job_failed(job, str(e))
            await ctx.supervisor.report_failure(worker_id, job, e)
        finally:
            ctx.queue.task_done()
```

**`process_rom` interno** (orden):
1. Chequear cache SQLite por `cache_key`. Si hay `scrape_result` reciente → emitir con `status=SKIPPED`, salir.
2. Ejecutar cascada de providers (Sección 4).
3. Si `NO_MATCH` y los providers por nombre no dieron: llamar a Hasheous, intentar de nuevo.
4. Descargar media en paralelo (`asyncio.gather` con `semaphore=ctx.media_concurrency`).
5. Persistir `ScrapedResult` en DB.
6. Persistir cada `MediaFile` en DB.
7. Persistir `text_provenance` por campo.
8. Devolver `JobResult` a la `result_queue`.

**Concurrencia interna por worker** para descarga de media: `--media-concurrency M`, default 4.

### 3.5 — Supervisor (recuperación de workers muertos)

```python
class Supervisor:
    def __init__(self, queue, ctx, max_attempts=3, backoff_base=2.0):
        self.failures: dict[str, list[datetime]] = defaultdict(list)
        self.dlq: list[Job] = []

    async def report_failure(self, worker_id: str, job: Job, error: Exception):
        self.failures[worker_id].append(datetime.utcnow())
        recent = [t for t in self.failures[worker_id]
                  if (datetime.utcnow() - t).total_seconds() < 60]
        if len(recent) >= 3:
            logger.error("worker_quarantined", worker=worker_id)
            self.dlq.append(job)
            return

        job.attempts += 1
        if job.attempts >= self.max_attempts:
            self.dlq.append(job)
            logger.warning("job_to_dlq", job=job.job_id, attempts=job.attempts)
        else:
            await asyncio.sleep(self.backoff_base ** job.attempts)
            await self.ctx.queue.put(job)
            logger.info("job_requeued", job=job.job_id, attempt=job.attempts)
```

- 1 fallo aislado → reintento con backoff (2s, 4s, 8s).
- 3 fallos del mismo worker en 60s → cuarentena, job a DLQ.
- 3 reintentos del mismo job → DLQ.
- DLQ → `run.failures.csv`.

### 3.6 — Manejo de SIGTERM / SIGINT

**Soft drain (default `--shutdown-timeout 180`)**:

1. `shutdown_event` se setea.
2. Workers NO toman nuevos jobs del `queue.get()`.
3. Cada worker **termina su job actual completo** (respetando el `phase` actual).
4. Si el job excede los 180 segundos, se cancela con `status=TIMED_OUT` y `error=shutdown_timeout`.
5. Jobs `PENDING` y `IN_PROGRESS` quedan persistidos con esos estados.
6. `runs.finished_at` se setea, `runs.status='aborted'`.
7. CLI imprime resumen + path a `--continue <run_id>`. Exit 130.

**Doble Ctrl+C** → cancela el drain, abandona jobs en `IN_PROGRESS`. Al reanudar, se re-encolan como `pending` (reintento desde cero).

**Cancelación durante DOWNLOADING**:
- Los archivos `.part` (durante descarga) se borran en el `finally` del handler de cancelación.
- La próxima corrida los regenera desde cero.

```python
async def safe_download(url, dest, session):
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        async with session.get(url) as resp:
            async with aiofiles.open(part, "wb") as f:
                async for chunk in resp.content.iter_chunked(64*1024):
                    await f.write(chunk)
        await aiofiles.os.replace(part, dest)
    except (asyncio.CancelledError, Exception):
        if part.exists():
            part.unlink(missing_ok=True)
        raise
```

### 3.7 — Result queue y CSV writer (streaming)

```python
async def csv_writer_task(csv_path, result_queue, db):
    writer = CsvWriter(csv_path)
    flush_every = 50
    buffer = 0
    while True:
        result = await result_queue.get()
        await writer.write_row(result)
        buffer += 1
        if buffer >= flush_every:
            await writer.flush()
            buffer = 0
        result_queue.task_done()
```

- Un solo writer (lock implícito en `result_queue`).
- Buffering de 50 filas entre flushes.
- Append-only desde el inicio del run.
- Cierre limpio en shutdown: flush final + `csv_file.close()`.

### 3.8 — Progress reporter (rich)

Muestra en tiempo real:
- Total ROMs / completadas / fallidas / ETA.
- Por worker: estado (idle / procesando / rate).
- Throughput: ROMs/min, MB/min.
- Por provider: % de uso.

### 3.9 — Checkpoint / Resume

**Trigger**: `multiscraper scrape --continue <run_id>`.

1. CLI lee `runs`, verifica `status='aborted'`.
2. Carga todos los `run_jobs` con `state IN ('pending','in_progress','failed')`.
3. Jobs `in_progress` → `pending` (reintento desde cero). Los archivos `.part` huérfanos del run anterior se borran al inicio del resume.
4. Jobs `failed` se omiten (quedan en log; `--include-failed` para reencolarlos).
5. Cache de `done` se respeta: esos jobs no se re-encolan, no se duplican en el CSV, y su `scrape_results` previa se preserva.
6. Orchestrator continúa con el mismo `run_id` y misma config.

No se reanuda un run con `status='running'`. Si el run previo terminó normalmente (`ok`/`partial`), `--continue` se rechaza con error claro.

### 3.10 — Configuración del orquestador (defaults)

```yaml
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

queue:
  max_size: 0
```

### 3.11 — Manejo de errores tipados

```python
class ScrapeError(Exception): pass
class ProviderError(ScrapeError): pass
class NetworkError(ScrapeError): pass
class ParseError(ScrapeError): pass
class BlockedError(ProviderError): pass
class AuthMissingError(ProviderError): pass
class RateLimitError(ProviderError):
    def __init__(self, retry_after: float | None = None): ...
class TransportError(ScrapeError): pass
class SshConnectionError(TransportError): pass
class SshAuthError(TransportError): pass
class FileAccessError(TransportError): pass
class ConfigError(Exception): pass
class ShutdownError(Exception): pass
class SoftTimeoutError(ShutdownError): pass
class HardTimeoutError(ShutdownError): pass
class HashError(ScrapeError): pass
class DownloadError(ScrapeError): pass
class NotFoundError(ProviderError): pass
```

---

## Sección 4 — Providers

### 4.1 — `Provider` Protocol

```python
# src/multiscraper/providers/base.py
from typing import Protocol, runtime_checkable
from multiscraper.models import Rom, Candidate, MediaRef, MediaType

@runtime_checkable
class Provider(Protocol):
    name: str
    requires_auth: bool
    auth_fields: list[str]
    rate_limit_per_sec: float
    priority: int

    supported_media: set[MediaType]
    platform_map: dict[str, str | int]
    is_identifier_only: bool = False
    is_offline: bool = False

    async def setup(self, config: dict) -> None: ...
    async def close(self) -> None: ...
    async def search(self, rom: Rom) -> list[Candidate]: ...
    async def fetch_media(
        self, candidate: Candidate, wanted: set[MediaType]
    ) -> dict[MediaType, MediaRef]: ...
    def detect_blocked(self, response, body: bytes) -> bool: ...
    def is_auth_missing(self, exc: Exception) -> bool: ...
```

`@runtime_checkable` permite `isinstance(p, Provider)`.

### 4.2 — `Identifier` sub-Protocol

```python
@runtime_checkable
class Identifier(Protocol):
    name: str
    async def identify(self, rom: Rom) -> IdentifierResult | None: ...

class IdentifierResult(BaseModel):
    canonical_name: str
    platform: str
    source_id: str
    provider: str
    confidence: float = 1.0
```

### 4.3 — Cascada de fallback

```python
async def process_rom(ctx, rom: Rom) -> ScrapedResult:
    # 1. Cache check
    cached = await ctx.db.get_cached_result(rom)
    if cached and not ctx.config.force_rescrape:
        return cached.with_status(SKIPPED)

    # 2. Identifier cascade (solo si los providers por nombre fallan)
    identified_name = rom.normalized_name
    primary_candidates: list[Candidate] = []

    for provider in ctx.media_providers_in_priority:
        if ctx.is_provider_blocked(provider):
            continue
        try:
            cands = await provider.search(rom, identified_name)
            # pick_best_with_language ordena por match_score + idioma + prioridad
            cands = sorted(cands, key=lambda c: pick_best_score(c, rom, ctx.config))
            primary_candidates = cands
            if cands and cands[0].match_score >= ctx.config.match_threshold:
                break
        except (BlockedError, RateLimitError) as e:
            await ctx.mark_provider_blocked(provider, e)
            continue
        except AuthMissingError:
            await ctx.disable_provider(provider, reason="auth_missing")
            continue
        except Exception as e:
            await ctx.record_provider_error(provider, e)
            continue

    # 3. Si ningún provider por nombre llegó al threshold → Hasheous
    if not primary_candidates or primary_candidates[0].match_score < ctx.config.match_threshold:
        for ident in ctx.identifier_providers:
            if ctx.is_provider_blocked(ident): continue
            try:
                res = await ident.identify(rom)
                if res and res.confidence >= 0.5:
                    identified_name = res.canonical_name
                    primary_candidates = await rerun_cascade(ctx, rom, identified_name)
                    primary_candidates.sort(key=lambda c: pick_best_score(c, rom, ctx.config))
                    break
            except Exception as e:
                await ctx.record_provider_error(ident, e)

    if not primary_candidates or primary_candidates[0].match_score < ctx.config.match_threshold:
        return ScrapedResult(rom=rom, status=NO_MATCH, identify_method=IdentifyMethod.NAME_ONLY, ...)

    # 4. Elegir el mejor candidato (considerando idioma)
    chosen = pick_best_with_language(primary_candidates, rom, ctx.config)

    # 5. Cascada de media
    wanted = ctx.requested_media_types
    media: dict[MediaType, MediaRef] = {}

    for media_type in wanted:
        for provider in ctx.media_providers_in_priority:
            if media_type not in provider.supported_media: continue
            if ctx.is_provider_blocked(provider): continue
            try:
                refs = await provider.fetch_media(chosen, {media_type})
                if media_type in refs:
                    media[media_type] = refs[media_type]
                    break
            except (BlockedError, RateLimitError) as e:
                await ctx.mark_provider_blocked(provider, e)
                continue

    # 6. Descargar media en paralelo
    media_files = await download_media_parallel(ctx, media, rom)

    return ScrapedResult(
        rom=rom,
        status=OK if len(media_files) >= ctx.config.partial_min_media else PARTIAL,
        identify_method=resolve_identify_method(rom, identified_by),
        chosen_provider=chosen.provider,
        match_score=chosen.match_score,
        metadata=extract_metadata(chosen, ctx.config),
        media=media_files,
        ...
    )
```

**Conceptos clave**:
- **Cascada de IDENTIFICACIÓN es independiente de la cascada de MEDIA**.
- **`match_threshold`**: si ningún candidato llega, `NO_MATCH`.
- **`pick_best`**: mayor `match_score`, luego más media disponible, luego region preference, luego prioridad del provider.

### 4.4 — Detección de bloqueo (Cloudflare / captcha)

```python
def detect_blocked(self, response, body) -> bool:
    if response.status in (403, 503, 429):
        body_lower = body.lower()
        if b"cloudflare" in body_lower or b"cf-ray" in body_lower:
            return True
        if b"captcha" in body_lower or b"challenge" in body_lower:
            return True
        if b"Just a moment" in body[:200]:
            return True
    return False
```

**Señales específicas por provider** (overrides):
- ScreenScraper: `<erreur>` con códigos de rate-limit.
- IGDB: status 429 con `X-RateLimit-Remaining=0`.
- GameFAQs: redirect a `/are-you-human` o página de captcha.
- OpenVGDB: 403 con `cf-ray` header.

**Políticas**:
- 3 fallos consecutivos en 60s → `provider_state.blocked_until = now() + cooldown`.
- Cooldown default: 30 min (`cooldown_after_blocked_sec: 1800`), configurable.
- Mientras esté bloqueado, el provider se salta en la cascada.
- Log: `event=provider_blocked, blocked_until=...`.
- Si todos los providers están bloqueados → `runs.status='paused'`.

### 4.5 — Rate-limit por provider

```python
class RateLimiter:
    """Token bucket asíncrono."""
    def __init__(self, rate_per_sec: float, burst: int = 1):
        self._rate = rate_per_sec
        self._capacity = max(1, burst)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
```

### 4.6 — Los 12 providers

| # | ID | Tipo | Auth | Media | Idiomas | Rate | Notas |
|---|---|---|---|---|---|---|---|
| 1 | `local_override` | media, offline | none | todos (vía paths locales) | configurable | N/A | Override curado, prioridad 1 |
| 2 | `hasheous` | identifier | none | N/A | N/A | 2/s | Lookup por hash |
| 3 | `screenscraper` | media | devid/devpassword (opcional) | todos (10 tipos) | en/fr/es/de/it/pt/jp | 2/s | Provider primario retro |
| 4 | `igdb` | media | Twitch OAuth2 | image, thumb, video | en (limitado local) | 4/s | Juegos modernos e indie |
| 5 | `rawg` | media | api_key | image, thumb, background | en | 5/s | Masivo moderno |
| 6 | `mobygames` | media | api_key | image, thumb, screenshot | en | 1/s | Metadata premium |
| 7 | `giantbomb` | media | api_key | image, video | en | 0.05/s | Video real, 200/h |
| 8 | `retroachievements` | media | api_key (web user) | image, logo | en | 1/s | NES/SNES/Genesis/etc. |
| 9 | `thegamesdb` | media | api_key v2 | image, fanart, screenshot, banner, logo | en | 1/s | Marcado experimental |
| 10 | `libretro_thumbnails` | media, offline | none | image, marquee, box3d, manual, logo | N/A | 0.5/s | Probeador de GitHub raw |
| 11 | `openvgdb` | media | none | image, screenshot | en (parcial) | 1/s | Sin auth, scraping HTML |
| 12 | `gamefaqs` | media | none | screenshot, desc | en (no etiquetado) | 0.5/s | Último recurso, Cloudflare |
| 13 | `local_fallback` | media, offline | none | todos (vía paths locales) | configurable | N/A | Último en cascada |

Nota: `local_override` y `local_fallback` son la misma implementación interna (tabla `source_overrides`), con prioridades distintas en `sources.yaml`. El conteo total es 13 entries: 11 proveedores de media únicos + 1 identifier (`hasheous`) + 1 provider local con doble rol.

### 4.7 — Configuración de providers (`sources.yaml`)

El bloque `language:` aplica por campo de texto. `text_priority` se usa para `desc` y `genre`; `name_priority` para `name`. Los campos sin preferencia de idioma (`developer`, `publisher`, `rating`, `releasedate`) usan el primer valor disponible. El `fallback_strategy` (`best_effort` o `strict`) se evalúa por campo independientemente.

```yaml
language:
  text_priority: [en, es, fr, de, it, pt, jp]
  name_priority: [en, es, jp, fr]
  fallback_strategy: best_effort       # best_effort | strict
  default_language: en
  detection_method: stopwords          # stopwords | langdetect | trust_provider

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

### 4.8 — `ProviderRegistry`

```python
class ProviderRegistry:
    def __init__(self):
        self._by_name: dict[str, Provider] = {}
        self._by_media_type: dict[MediaType, list[Provider]] = defaultdict(list)
        self._identifiers: list[Identifier] = []

    def register(self, p: Provider):
        self._by_name[p.name] = p
        for mt in p.supported_media:
            self._by_media_type[mt].append(p)
        if isinstance(p, Identifier):
            self._identifiers.append(p)

    def providers_for_media(self, mt: MediaType) -> list[Provider]:
        return sorted(self._by_media_type[mt], key=lambda p: p.priority)
```

### 4.9 — Negociación de idioma por campo y entre providers

**Defaults de prioridad por campo**:

| Campo | Prioridad | Notas |
|---|---|---|
| `name` | `language.name_priority` | Títulos localizados |
| `desc` | `language.text_priority` | Descripción larga |
| `genre` | `language.text_priority` | A veces sin etiquetar |
| `developer` | sin preferencia (nombre propio) | — |
| `publisher` | sin preferencia (nombre propio) | — |

**Algoritmo de selección**:
```
1. Por cada provider en la cascada, en orden de prioridad:
   2. Preguntar por cada idioma de la priority list, en orden.
      3. Si el provider devuelve un campo de texto en ese idioma → usarlo, parar.
   4. Si ninguno de los idiomas preferidos fue satisfecho, marcar como "gap" y seguir con el siguiente provider SOLO si el gap sigue sin llenarse.
2. Si tras todos los providers sigue el gap y fallback_strategy = best_effort, tomar el primer texto disponible en cualquier idioma.
```

**Detección de idioma**:
- Si el provider etiqueta idioma: confiar.
- Si no: heurística de stopwords (EN/ES/FR/DE/IT/PT/JP, ~100 palabras cada uno).
- Opcional: `langdetect` como dependencia condicional.
- Si confianza < 0.6 → "idioma desconocido", al final de la priority list.

**`pick_best_with_language` criterios de ordenamiento**:
1. `match_score` (desc).
2. ¿`name` está en `name_priority[0]`? (preferir sí).
3. ¿`desc` está en `text_priority[0]`? (preferir sí).
4. Prioridad del provider (asc).

---

## Sección 5 — Manejo de errores, fallbacks, modos de fallo

### 5.1 — Mapeo excepción → status

| Excepción | Status CSV | Columna `error` |
|---|---|---|
| `AuthMissingError` | `ERROR` | `auth_missing:<provider>` |
| `BlockedError` | `BLOCKED` | `provider_blocked:<provider>` |
| `RateLimitError` | `BLOCKED` | `rate_limited:<provider>:retry_after=<s>` |
| `NotFoundError` | `NO_MATCH` | `not_found:<provider>` |
| `ParseError` | `ERROR` | `parse_error:<provider>:<class>` |
| `NetworkError` | `ERROR` | `network:<class>` |
| `HashError` | `ERROR` | `hash_failed` |
| `DownloadError` | `PARTIAL` | `download_failed:<type>:<url>` |
| `HardTimeoutError` | `TIMED_OUT` | `shutdown_timeout` |
| `SoftTimeoutError` | `ERROR` | `shutdown_forced` |
| `TransportError` | `ERROR` | `transport:<subclass>` |
| `ConfigError` | aborta el run | `config_invalid` |

### 5.2 — Todos los providers bloqueados

1. Mientras quede ≥1 provider disponible, el run continúa.
2. Si todos los providers de media están bloqueados:
   - `runs.status = "paused"`.
   - Mensaje en stderr con ETA del próximo desbloqueo.
   - Cooldown más próximo desbloquea → `--auto-resume-on-unblock` (default OFF) puede reanudar.
3. Si `--auto-resume-on-unblock` está OFF, el run queda pausado y el usuario decide.
4. Jobs afectados → `status=BLOCKED`, van al DLQ con `provider_blocked_at_pause`.

### 5.3 — `NO_MATCH`

1. No se crea `ScrapedResult` con `OK|PARTIAL`. Solo con `status=NO_MATCH`.
2. No se descarga media.
3. No se escribe `<game>` en `gamelist.xml` (solo `<path>`).
4. Sí se registra en CSV con `status=NO_MATCH`, `chosen_provider=NULL`, columnas de media vacías.
5. Sí se registra en SQLite (`scrape_results` con `metadata_json=NULL`).
6. Se incluye en `summary.json.per_system[<sys>].no_match`.

**Cumple "si no se puede determinar el juego no se hace nada"**.

### 5.4 — `PARTIAL`

`status=PARTIAL` cuando hay metadata + ≥1 media pero no todos los `required_media_types`.

```yaml
output:
  partial_min_media: 3
  required_media_types: [image]    # image es OBLIGATORIO para OK
```

Reglas de promoción a `OK`:
- `OK` requiere: `image` está en media descargada AND `len(media_files) >= partial_min_media`.
- `PARTIAL` es: al menos 1 media descargado AND no cumple las dos condiciones de OK.
- Sin media pero con metadata válida → `PARTIAL` también (la metadata es lo único que se preserva).
- Sin metadata y sin media → `NO_MATCH` (no es `PARTIAL`).

### 5.5 — `local_override` y `local_fallback`

#### `local_override` (prioridad 1, antes de internet)
1. ¿`cache_key` en `source_overrides`? → usar metadata directamente, no llamar a providers online.
2. `image_path` local → copiar a `media_root/<system>/<rom>-image.<ext>`.
3. Mezcla permitida: si override tiene `name,desc` pero no `developer`, la cascada puede completar.

#### `local_fallback` (último, después de todos los providers)
- Si `primary_candidates` está vacío o todos `match_score < threshold` → buscar en `source_overrides`.
- Si hay match → usarlo.
- Si no → `NO_MATCH`.

### 5.6 — Tabla resumen de comportamiento por caso

| Caso | Status CSV | Media | gamelist.xml | summary.json |
|---|---|---|---|---|
| Match perfecto, todos los media | `OK` | todos | `<game>` completo | `ok` |
| Match, algunos media faltan | `PARTIAL` | los que se pudo | `<game>` parcial | `partial` |
| Sin match en ningún provider | `NO_MATCH` | nada | solo `<path>` | `no_match` |
| Provider bloqueado, no se intentó | `BLOCKED` | nada | no aparece | `blocked` |
| Error recuperable (red) | `ERROR` | parcial si hubo | depende | `error` |
| Shutdown timeout (hard) | `TIMED_OUT` | parcial si hubo | depende | `timed_out` |
| Ya en cache, `--skip-existing` | `SKIPPED` | nada | el que ya estaba | `skipped` |
| `local_override` hit | `OK` o `PARTIAL` | los del override | `<game>` con override | según status |
| `local_fallback` hit | `OK` o `PARTIAL` | los del override | igual | según status |

### 5.7 — Health checks y alertas

`RunTotals` incluye:
- `error_breakdown: dict[str, int]`
- `by_status: dict[ScrapeStatus, int]`
- `by_provider_match: dict[str, int]`
- `avg_match_score`, `p50_match_score`, `p95_match_score`
- `avg_elapsed_ms_per_rom`
- `throughput_roms_per_min`, `throughput_mb_per_min`

**Alerta de low match rate**:
- Si `avg_match_score < 0.5` o `roms_no_match / roms_total > 0.3`:
  - `runs.status = "partial"`.
  - `summary.json.warnings` con tipo `low_match_rate`, sistema, métrica, valor, threshold, sugerencia.

### 5.8 — Reglas de llenado de columnas CSV

| Columna | Cuándo se llena | Vacía |
|---|---|---|
| `error` | Solo si `status ∈ {ERROR, BLOCKED, TIMED_OUT}` | Otros |
| `warnings` | Cualquier `status` con advertencias | Sin warnings |
| `identify_method` | Siempre | Nunca |
| `match_score` | Si hubo match | `NO_MATCH`/`BLOCKED`/`SKIPPED` |
| `chosen_provider` | Si hubo match | `NO_MATCH`/`BLOCKED`/`SKIPPED`/`TIMED_OUT` |
| `elapsed_ms` | Siempre | Nunca |
| `fetched_at` | Siempre | Nunca |
| Columnas de media | Si se intentó descargar | Si no llegó a fase de media |

**Regla de oro**: cada fila es una proyección de `JobResult` (que ya tiene el `ScrapedResult` construido). CSV y DB nunca se contradicen.

---

## Sección 6 — Estructura, CLI, testing, deps, criterios de aceptación

### 6.1 — Estructura de directorios final

```
multiscraper/                              # raíz del repo
├── pyproject.toml
├── README.md
├── LICENSE                                 # MIT
├── CHANGELOG.md
├── .gitignore
├── .editorconfig
├── config/
│   ├── sources.example.yaml
│   └── systems.example.yaml
├── docs/
│   ├── README.md
│   ├── architecture.md
│   ├── configuration.md
│   ├── cli.md
│   ├── adding-a-provider.md
│   ├── ssh-setup.md
│   ├── ems_files.md
│   ├── logging.md
│   ├── research/
│   │   ├── emulationstation.md
│   │   ├── screenscraper-api.md
│   │   └── alternatives.md
│   └── plans/
│       └── 2026-07-22-multiscraper-impl.md
├── src/
│   └── multiscraper/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── logging_setup.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   ├── models.py
│       │   ├── es_systems_parser.py
│       │   └── validation.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── orchestrator.py
│       │   ├── job.py
│       │   ├── queue.py
│       │   ├── worker.py
│       │   ├── supervisor.py
│       │   ├── batcher.py
│       │   ├── shutdown.py
│       │   ├── checkpoint.py
│       │   └── rate_limiter.py
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── local.py
│       │   ├── ssh.py
│       │   └── pool.py
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── normalize.py
│       │   ├── match.py
│       │   ├── cascade.py
│       │   ├── block_detect.py
│       │   ├── screenscraper.py
│       │   ├── igdb.py
│       │   ├── rawg.py
│       │   ├── mobygames.py
│       │   ├── giantbomb.py
│       │   ├── retroachievements.py
│       │   ├── thegamesdb.py
│       │   ├── libretro_thumbnails.py
│       │   ├── openvgdb.py
│       │   ├── gamefaqs.py
│       │   ├── hasheous.py
│       │   └── local.py
│       ├── output/
│       │   ├── __init__.py
│       │   ├── db.py
│       │   ├── models.py
│       │   ├── csv_writer.py
│       │   ├── media_writer.py
│       │   ├── gamelist_xml.py
│       │   ├── summary.py
│       │   ├── log_jsonl.py
│       │   └── name_normalize.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── noop.py
│       │   └── openai_compat.py
│       └── utils/
│           ├── __init__.py
│           ├── hash.py
│           ├── http.py
│           ├── fs.py
│           └── retry.py
└── tests/
    ├── conftest.py
    ├── cassettes/
    ├── fixtures/
    ├── unit/
    └── integration/
```

### 6.2 — Comandos CLI

#### `multiscraper scrape`
```
multiscraper scrape [OPTIONS]

  --roms-root PATH
  --media-root PATH                 # default: $HOME/multiscraper_data/media
  --es-systems PATH
  --config PATH                     # default: ./config/sources.yaml
  --systems snes,psx
  --exclude-systems mame
  --workers N                       # default: 8
  --media-concurrency N             # default: 4
  --batch-size N                    # default: 50
  --match-threshold FLOAT           # default: 0.7
  --hash crc32|sha1|auto            # default: auto
  --region wor,us,eu,jp             # default: wor,us,eu,jp
  --language en,es                  # default: en
  --media image,video,marquee       # subset; default: todos
  --no-media
  --skip-existing
  --force-rescrape
  --continue RUN_ID
  --shutdown-timeout N              # default: 180
  --provider-cooldown-sec N         # default: 1800
  --auto-resume-on-unblock
  --ssh-host HOST
  --ssh-user USER
  --ssh-key PATH
  --ssh-port N                      # default: 22
  --ssh-jump user@host
  --auto-trust
  -v, --verbose
  -vv
  -q, --quiet
  --log-file PATH
  --csv PATH
  --emit es|json|both               # default: both
  --dry-run
  --no-language-columns
```

#### Otros comandos
- `multiscraper validate-config`
- `multiscraper convert-to-es --run-id RUN_ID [--out PATH] [--systems ...]`
- `multiscraper list-systems [--es-systems PATH] [--roms-root PATH]`
- `multiscraper db {stats, vacuum, reset, show-rom, show-run, cleanup-runs}`
- `multiscraper override {add, list, remove, import, export}`
- `multiscraper doctor`

### 6.3 — Dependencias

#### Runtime
| Paquete | Versión mín | Para qué |
|---|---|---|
| `aiohttp` | ≥3.9 | HTTP async |
| `asyncssh` | ≥2.13 | SSH async |
| `pydantic` | ≥2.5 | modelos y validación |
| `click` | ≥8.1 | CLI |
| `rich` | ≥13.6 | progress + logging handler |
| `lxml` | ≥5.0 | XML parsing |
| `PyYAML` | ≥6.0 | config |
| `aiosqlite` | ≥0.19 | SQLite async |
| `aiofiles` | ≥23.2 | file I/O async |
| `charset-normalizer` | ≥3.3 | encoding detection |
| `python-ulid` | ≥2.2 | IDs |
| `Pillow` | ≥10.0 | opcional, resize |
| `python-dateutil` | ≥2.8 | fechas |

#### Dev
`pytest`, `pytest-asyncio`, `pytest-cov`, `vcrpy`, `aioresponses`, `mypy`, `ruff`, `types-PyYAML`, `types-aiofiles`, `freezegun`.

#### Entry points
```toml
[project.scripts]
multiscraper = "multiscraper.cli:main"

[project.entry-points."multiscraper.providers"]
# Para que third parties agreguen providers vía pip install
```

### 6.4 — `pyproject.toml`

```toml
[project]
name = "multiscraper"
version = "0.1.0"
description = "Parallel, multi-source scraper for retro gaming frontends"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "fr4j4"}]
keywords = ["emulationstation", "scraper", "retro", "gaming", "roms"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Games/Other Games",
    "Topic :: Multimedia :: Graphics",
]

dependencies = [
    "aiohttp>=3.9",
    "asyncssh>=2.13",
    "pydantic>=2.5",
    "click>=8.1",
    "rich>=13.6",
    "lxml>=5.0",
    "PyYAML>=6.0",
    "aiosqlite>=0.19",
    "aiofiles>=23.2",
    "charset-normalizer>=3.3",
    "python-ulid>=2.2",
    "Pillow>=10.0",
    "python-dateutil>=2.8",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "vcrpy>=5.1",
    "aioresponses>=0.7",
    "mypy>=1.8",
    "ruff>=0.3",
    "types-PyYAML",
    "types-aiofiles",
    "freezegun>=1.4",
]

[project.scripts]
multiscraper = "multiscraper.cli:main"

[project.entry-points."multiscraper.providers"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/multiscraper"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "network: requires internet access",
    "slow: long-running tests",
]
```

### 6.5 — Convenciones de código

- **Python ≥ 3.11** (`asyncio.TaskGroup`, `tomllib`, `ExceptionGroup`).
- **Type hints estrictos**, `mypy --strict` en CI.
- **Ruff** con config: line-length 100, target py311, reglas E/F/W/I/UP/B/SIM/RUF.
- **Sin comentarios en código** salvo docstrings.
- **Docstrings** formato Google para funciones públicas.
- **Módulos pequeños**: ningún archivo > 400 líneas; si crece, dividir.
- **Tests primero** para lógica nueva.

### 6.6 — Testing

- **`pytest` + `pytest-asyncio`**.
- **Pirámide**: E2E (1-2), integración (10-15), unit (50+).
- **Cobertura objetivo**: `core/` > 90%, `providers/` > 80%, `output/` > 85%, `transport/` > 80%.
- **Cassettes `vcrpy`** en `tests/cassettes/<provider>/<test_name>.yaml`.
- **Fakes** para tests unit (FakeProvider, MockSshTransport).
- **Sin red en CI**: `pytest -m "not network" -m "not slow"`.
- **Marcadores**: `@pytest.mark.network`, `@pytest.mark.slow`, `@pytest.mark.provider_X`.

### 6.7 — Criterios de aceptación de v1

**Funcionales**:
1. Lee `es_systems.cfg` o `systems.yaml` y descubre sistemas + ROMs.
2. Se conecta por SSH a la arcade (asyncssh) y lista ROMs sin descargarlas.
3. Calcula CRC32 sobre los primeros 4KB, escala a SHA1 si hay colisión.
4. Consulta ScreenScraper primero, fallback a IGDB/MobyGames/etc.
5. Si ningún provider identifica → Hasheous → NO_MATCH.
6. Descarga `image, thumbnail, video, marquee, box3d, backcover, fanart, manual, miximage, logo`.
7. Detecta Cloudflare/captcha y salta a siguiente provider tras 3 fallos.
8. Si todos los providers están bloqueados, pausa el run con mensaje claro.
9. Genera CSV streaming con una fila por ROM y columnas por media type.
10. Persiste en SQLite con WAL, migraciones versionadas.
11. Genera `gamelists/<system>/gamelist.xml` compatible con ES.
12. Guarda media en `$HOME/multiscraper_data/media/<system>/<rom>-<type>.<ext>`.
13. Soporta `local_override` (prioridad 1) y `local_fallback` (último).
14. Interfaz `TextGenerator` con `NoOp` default; `OpenAICompat` cableada pero inactiva.
15. Maneja SIGTERM/SIGINT con drain de 3 min, status `TIMED_OUT` si se excede.
16. Reanuda runs abortados con `--continue <run_id>`.
17. Logging stdlib a terminal (Rich) y a archivo JSONL.
18. Cobertura > 80% global, > 90% en `core/`.
19. Idioma preferente con fallback configurable por campo (name, desc, genre).

**No funcionales**:
- Python 3.11+, type hints estrictos, mypy --strict pasa.
- Ruff sin warnings.
- Sin red en CI (todos los tests con cassettes o fakes).
- Documentación en `docs/` (inglés).
- Licencia MIT.

### 6.8 — Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| ScreenScraper cambia su API | Cassettes versionadas; `Provider` Protocol aísla el cambio |
| `asyncssh` queda sin mantenimiento | Plan B: `paramiko` + `asyncio.to_thread`; `Transport` Protocol aísla |
| Cloudflare agresivo | Detección + cooldown + auto-pausa |
| DB enorme con miles de ROMs | WAL + índices + `cleanup-runs` |
| SSH connection drops | Reconexión con backoff; run no aborta |
| Cassettes desactualizados | Marcador `@pytest.mark.network` para regenerar; CI los salta |
| Provider devuelve data basura | `match_threshold` + `local_override` |

### 6.9 — Roadmap post-v1

- Resize automático de imágenes grandes.
- Hash completo (no primeros 4KB) opcional.
- Soporte para `pegasus-frontend` y `LaunchBox` como targets.
- UI web ligera para monitorear runs.
- Modo daemon que escucha cambios en ROMs.
- Hasheous server self-hosted.
- LLM para mejorar descripciones (activar `OpenAICompatTextGenerator`).
- Provider TheGamesDB v2 cuando estabilice.
- Caché compartida entre PCs (`multiscraper db sync`).

---

## Apéndice A — Refinamiento de idiomas (integrado en Sección 4.9)

El diseño de idiomas permite que el usuario defina:

- `text_priority: [en, es, fr, ...]` — para descripciones y géneros.
- `name_priority: [en, es, jp, ...]` — para nombres de juegos.
- `fallback_strategy: best_effort | strict`.
- `default_language: en`.
- `detection_method: stopwords | langdetect | trust_provider`.

El algoritmo de cascada (4.3 + 4.9) consulta providers en orden de prioridad y, dentro de cada provider, prueba idiomas en orden de `text_priority`/`name_priority`. La heurística de stopwords se usa cuando el provider no etiqueta el idioma. La detección con `langdetect` queda como dependencia opcional y condicional.

La provenance de idioma se persiste en la tabla `text_provenance` (ver 2.2) y se proyecta al CSV en las columnas `name_language`, `desc_language`, `desc_source`, `genre_language`, `genre_source`, `language_warnings`.

## Apéndice B — Referencias de investigación

- **EmulationStation / RetroPie**: https://github.com/RetroPie/EmulationStation
- **GAMELISTS.md**: https://github.com/RetroPie/EmulationStation/blob/master/GAMELISTS.md
- **ScreenScraper.cpp** (mapeo de media): https://github.com/RetroPie/EmulationStation/blob/master/es-app/src/scrapers/ScreenScraper.cpp
- **GamesDBJSONScraperResources.cpp**: https://github.com/RetroPie/EmulationStation/blob/master/es-app/src/scrapers/GamesDBJSONScraperResources.cpp
- **SYSTEMS.md**: https://github.com/RetroPie/EmulationStation/blob/master/SYSTEMS.md
- **ScreenScraper API v2**: https://www.screenscraper.fr/api.php
- **Skraper** (alternativa community): https://www.skraper.net/
- **IGDB API**: https://api-docs.igdb.com/
- **RAWG API**: https://api.rawg.io/docs/
- **MobyGames API**: https://www.mobygames.com/info/api/
- **GiantBomb API**: https://www.giantbomb.com/api/
- **RetroAchievements API**: https://api-docs.retroachievements.org/
- **TheGamesDB**: https://thegamesdb.net/
- **LibRetro Thumbnails**: https://github.com/libretro-thumbnails
- **OpenVGDB**: https://vgdb.io/
- **Hasheous**: https://hasheous.org/
- **asyncssh**: https://asyncssh.readthedocs.io/
- **Python asyncio docs**: https://docs.python.org/3/library/asyncio.html
- **Pydantic v2**: https://docs.pydantic.dev/latest/
- **SQLite WAL**: https://www.sqlite.org/wal.html
- **vcrpy**: https://vcrpy.readthedocs.io/

---

## Apéndice C — Plan de implementación (referencia rápida)

El detalle paso-a-paso se generará con la skill `writing-plans` después de aprobar este spec. La estructura objetivo:

1. Scaffold del proyecto (`pyproject.toml`, estructura, CLI vacío).
2. Modelos Pydantic (Sección 2.1) y utils base (hash, retry, http, fs).
3. Capa de transporte: `LocalTransport` y `SshTransport` con pool.
4. Sistema de config: carga YAML, parseo de `es_systems.cfg`, validación.
5. Output layer: SQLite con migraciones, CSV writer, gamelist.xml, summary, log JSONL.
6. Provider Protocol + Identifier Protocol + registry + normalize + match.
7. Implementación de los 12 providers (uno por uno, con tests).
8. Cascade logic con idioma.
9. Orchestrator + queue + batcher.
10. Worker + Supervisor + checkpoint.
11. Shutdown handling (SIGTERM, drain, timeout).
12. CLI completa con todos los flags.
13. Documentación (`docs/*.md`).
14. Tests e2e con cassettes.
15. Empaquetado y entry points.
