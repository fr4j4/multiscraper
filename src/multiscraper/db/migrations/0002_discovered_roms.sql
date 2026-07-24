-- Temporary per-run index used to pipeline discovery → workers.
-- Truncated at the START and END of every scrape. Not a source of
-- truth for "already scraped"; that lives in roms + scrape_results.

CREATE TABLE IF NOT EXISTS discovered_roms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    system          TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    raw_name        TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    size            INTEGER NOT NULL,
    mtime           INTEGER NOT NULL,
    crc32           TEXT,
    sha1            TEXT,
    cache_key       TEXT,
    hash_status     TEXT NOT NULL CHECK (hash_status IN
                        ('pending','done','skipped','failed','claimed','completed')),
    skip_reason     TEXT,
    claimed_at      TEXT,
    UNIQUE (run_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_disc_run_system_status
    ON discovered_roms(run_id, system, hash_status);
CREATE INDEX IF NOT EXISTS idx_disc_claimed_at
    ON discovered_roms(claimed_at);
CREATE INDEX IF NOT EXISTS idx_disc_run_rel
    ON discovered_roms(run_id, system, rel_path);
