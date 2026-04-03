# Local Kline Cache

## Purpose

The local K-line loader is split into two layers:

- `strategy/kline_reader.py`
- `strategy/kline_lru_adapter.py`

`strategy/local_kline_cache.py` remains as a thin compatibility re-export for the old import path.

The cache layer is responsible for:

- loading individual CSV files lazily
- keeping recently used file payloads in memory
- enforcing a maximum in-memory size
- evicting least-recently-used files when the byte limit is exceeded

The cache layer is **not** responsible for strategy warm-up logic, evaluation windows, or thread safety.

## Design

There are three relevant modules:

1. `LocalKlineReader`
   - filesystem reader and normalizer for local K-line CSV files
   - lives in `strategy/kline_reader.py`
   - does not depend on the LRU implementation
2. `MemorySizedLruCache`
   - generic, non-thread-safe, byte-limited LRU cache
   - lives in `strategy/memory_lru_cache.py`
3. `LocalKlineDataCache`
   - domain adapter for local K-line directories
   - lives in `strategy/kline_lru_adapter.py`
   - wraps `LocalKlineReader` and uses the generic LRU cache to store normalized per-file `DataFrame` payloads

## Cache Unit

The cache unit is a single CSV file.

- `kline_day/<CODE>/<CODE>_YYYY-MM-DD.csv`
- `kline_minute/<CODE>/<CODE>_YYYY-MM-DD.csv`

The LRU key is:

- `(frame_type, code, path)`

This means:

- daily and minute files are cached by the same mechanism
- different symbols do not collide
- the cache can evict one file without invalidating all history for the symbol

## Memory Limit

`LocalKlineDataCache` accepts:

```python
LocalKlineDataCache(max_cache_bytes=512 * 1024 * 1024)
```

Default is `512 MiB`.

It can also disable file-level caching entirely:

```python
LocalKlineDataCache(enable_file_cache=False)
```

When disabled:

- CSV files are still normalized through the same code path
- no per-file payload is retained in memory
- cache stats such as `current_bytes`, `peak_bytes`, `cached_files`, `hit_count`, and `miss_count` stay at `0`
- `set_csv_frame()` / `set_history_frame()` are unavailable, because there is no backing file cache to warm

Each cached file uses:

```python
int(frame.memory_usage(index=True, deep=True).sum())
```

When inserting a new file would push the cache above `max_cache_bytes`, the cache evicts the least recently used files until:

- `current_bytes <= max_bytes`

If a single file is larger than the configured cache limit, that file is returned to the caller but is not cached.

## Read Path

`get_daily_csv_frame(code)` and `get_minute_csv_frame(code)`:

1. enumerate the CSV files under the symbol directory
2. fetch each file from the file-level LRU cache
3. on cache miss, load that file from disk and put it into the LRU cache
4. merge the per-file frames into one normalized symbol-level frame

This keeps the reusable unit at file granularity while preserving the existing public API.

`LocalKlineReader` exposes the same read APIs without any file-level LRU. `LocalDataDailyHistoryProvider` now uses the pure reader by default, while `CachedRemoteDailyHistoryProvider` explicitly opts into `LocalKlineDataCache` so it can warm and reuse local daily payloads.

For live warm-up paths that only need the most recent bars, the cache also exposes tail-oriented reads:

- `get_daily_csv_tail_frame(code, rows)`
- `get_daily_history_tail_frame(code, rows)`

Those methods scan files from newest to oldest and stop once the latest `rows` records can be reconstructed, which avoids loading the full local history for large `kline_day/<CODE>/` directories.

## Write Path

`set_csv_frame()` and `set_history_frame()`:

1. normalize the full symbol frame
2. split the frame back into file-sized payloads
3. verify every payload fits within `max_cache_bytes`
4. evict any cached files for that `(frame_type, code)`
5. warm the LRU cache with those file payloads

Split rules:

- `day`: one cached payload per week-start file
- `minute`: one cached payload per trade-date file

This matches the repository's on-disk layout.

If any single payload is larger than the configured cache limit, the write raises `ValueError` and leaves the existing cache contents unchanged for that symbol.

## Stats

`LocalKlineReader.snapshot()` returns:

- `total_load_seconds`
- `files_loaded`
- `load_operations`

`LocalKlineDataCache.snapshot()` extends that with:

- `total_load_seconds`
- `files_loaded`
- `load_operations`
- `current_bytes`
- `peak_bytes`
- `max_bytes`
- `cached_files`
- `hit_count`
- `miss_count`
- `eviction_count`

Notes:

- `current_bytes` / `peak_bytes` only describe the file cache itself
- they do not include downstream derived arrays such as EMA, RSI, or unified minute timelines

## Non-Goals

Current implementation intentionally does not do these things:

- thread safety
- arbitrary time-range-aware file selection
- strategy warm-up calculation
- process-wide memory accounting outside the cache

Those belong to higher layers.
