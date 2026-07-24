# Discovery

Discovery is the part of a scrape that turns "list of files on disk or
over SSH" into rows the orchestrator can consume. As of v2 it runs in
parallel with the worker pool, removing the serial startup cost on
large collections.

## Why it changed

The original flow did discovery strictly before starting any workers:

```
list_dir -> for each file: file_info + hash -> build Rom -> enqueue
                                                                  ^
                                                                  workers wait
```

For a system with 5,000 ROMs over SSH, that meant 5,000 sequential
round-trips before the first worker ran. On a Pi-class host with a
`crc32` streamed from SFTP, the user could wait several minutes before
seeing any progress.

## The new flow

Discovery and workers run concurrently in the same `asyncio.run`:

```
1. truncate discovered_roms
2. create runs row
3. asyncio.create_task(_discover_all(...))   # discovery task
4. for each system: orchestrator.start(...)   # workers claim rows
5. await discovery_task
6. truncate discovered_roms (final cleanup)
```

The `discovered_roms` table is the channel between the two:

| hash_status   | set by                              | visible to         |
|---------------|-------------------------------------|--------------------|
| `pending`     | discovery (bulk insert)             | nothing            |
| `done`        | discovery (after hash completes)    | workers (claim)    |
| `failed`      | discovery (hash error)              | workers (claim)    |
| `claimed`     | worker (atomic claim)               | nothing            |
| `completed`   | worker (after processing)           | nothing            |

Workers call `claim_one_discovered` which atomically flips the next
ready row to `claimed`. Discovery has no awareness of the workers; it
just transitions `pending` -> `done`/`failed` as fast as it can.

The table is **truncated at the start and end of every run**. It is
not a source of truth for "already scraped" — that lives in `roms` +
`scrape_results`. The table exists only to pipeline discovery into
workers.

## Concurrency

Three knobs in `config.yaml::orchestrator`:

- `discovery_concurrency_ssh: 8` — semaphore around `SshTransport.hash`.
  Don't go too high; the SSH channel can be saturated.
- `discovery_concurrency_local: 32` — `LocalTransport._hash_sync` is
  already offloaded to the default `ThreadPoolExecutor`, so `gather`
  parallelizes naturally.
- `discovery_poll_interval_sec: 0.5` — workers sleep this long when
  no rows are claimable. Lower = more responsive, more DB polls.

## Skip-before-hash

For each file, before computing the CRC32, discovery consults the
`roms` table for an existing row with the same `(system, rel_path)`.
If that row has a non-null `crc32`, the file's `size` and `mtime`
match the cached values, and the file's `mtime` is not older than
the most recent successful scrape, the hash is skipped entirely. The
row is filled with the cached `cache_key`/`crc32`/`sha1` and marked
`done`. The worker then applies the existing skip path and the row
is recorded as SKIPPED in `scrape_results`.

This is the biggest win on warm caches: a 5,000-ROM collection where
4,800 are already OK drops from minutes of SSH hashing to a few
seconds of `list_dir` + 1 bulk `SELECT`.

### Decision table

| Condition                                       | Hash? |
|--------------------------------------------------|-------|
| `cached` is None (rom is new)                    | yes   |
| `cached.crc32` is NULL (hash failed previously)  | yes   |
| `cached.size != file_size`                      | yes   |
| `cached.mtime != file_mtime`                    | yes   |
| `cached.last_scrape_at` is NULL (no scrape yet) | yes   |
| `file_mtime < last_scrape_at` (cp -p case)      | yes   |
| `file_mtime >= last_scrape_at` and all match    | no    |
| `--force-rescrape` is set                       | yes   |

The `file_mtime >= last_scrape_at` check defends against `cp -p`
preserving a source file's mtime that is older than the destination
file's mtime: in that case the cached row's `mtime` matches the
file's, but the source may have been modified between the previous
scrape and the copy, so the hash is recomputed.

## Where the limits are

- Workers stop as soon as discovery is done AND there are no rows in
  `pending` or `claimed` states. The orchestrator receives a
  `discovery_done: asyncio.Event` from the scrape layer.
- The `--limit` flag and `--skip-existing`/`--force-rescrape` flags
  work the same way they did before; the only change is that they're
  enforced one row at a time as workers claim from the table. Note
  that `--force-rescrape` now also forces a re-hash in discovery, not
  just a re-cascade in the worker.
- On hard shutdown (SIGTERM twice) the table is left as-is. The next
  run's truncate cleans up.
