
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));

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
