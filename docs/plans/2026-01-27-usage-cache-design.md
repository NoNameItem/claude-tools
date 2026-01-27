# Usage Cache Refactoring

**Task:** claude-tools-5dl.10 — usage_limits возвращает None когда TTL истёк, но rate limit активен

**Date:** 2026-01-27

## Problem

The current cache implementation returns None when:
1. Cache TTL (60s) expires
2. Rate limit (30s) prevents API fetch
3. `load()` checks TTL and returns None for stale cache

This creates a window where valid cached data exists but the module returns nothing.

### Race Conditions

Multiple Claude Code windows share the same cache files. The current two-file design (`usage_limits.json` + `usage_limits.lock`) creates race conditions:
- Two processes read lock simultaneously, both decide to fetch
- Partial file writes cause read failures

## Solution

### Single File Design

Merge cache data and rate limit timestamp into one file:

```json
{
  "data": {
    "five_hour": {"utilization": 45.5, "resets_at": "2024-01-27T15:00:00Z"},
    "seven_day": {"utilization": 23.2, "resets_at": "2024-01-31T00:00:00Z"},
    "seven_day_sonnet": {"utilization": 12.1, "resets_at": "2024-01-31T00:00:00Z"}
  },
  "fetched_at": "2024-01-27T12:00:00Z"
}
```

- `data` — API response (null if fetch failed and no prior cache)
- `fetched_at` — timestamp for rate limiting (replaces lock file)

### New Logic

**Refresh first, then read:**

```python
def _get_usage_data(self):
    cache = self._load_cache()

    if self._can_fetch(cache):
        new_data = fetch_usage_api(token)
        data = new_data if new_data else (cache.data if cache else None)
        self._save_cache(data=data, fetched_at=now())
        return data

    return cache.data if cache else None
```

**Key changes:**
1. Remove TTL — cache always valid
2. Remove lock file — use `fetched_at` from cache
3. Order: refresh first, then read
4. Failed fetch: keep old data, update `fetched_at`

### Scenarios

| Scenario | Result |
|----------|--------|
| First launch, fetch succeeds | Return fresh data |
| First launch, fetch fails | Return None |
| Within rate limit | Return cached data |
| After rate limit, fetch succeeds | Return fresh data |
| After rate limit, fetch fails | Return stale data |

### Atomic Writes

Write to temp file, then rename:

```python
import tempfile

def _save_cache(self, data, fetched_at):
    cache_data = {"data": serialize(data), "fetched_at": fetched_at.isoformat()}

    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=self.cache_dir,
        suffix='.tmp',
        delete=False
    ) as f:
        f.write(json.dumps(cache_data))
        temp_path = Path(f.name)

    temp_path.rename(self.cache_file)
```

This prevents partial reads during concurrent access.

## Files to Change

- `packages/statuskit/src/statuskit/modules/usage_limits.py`
  - `UsageCache.load()` — remove TTL check
  - `UsageCache.save()` — atomic write
  - `UsageCache.can_fetch()` — read from cache file
  - Remove `mark_fetched()` — merged into save
  - Remove lock file handling
  - `UsageLimitsModule._get_usage_data()` — new logic

## Future: Usage History

A separate task (claude-tools-5dl.12) will add usage history for plan recommendations. This refactoring prepares the foundation by establishing a clean single-file cache design.

### Volume Estimates

**Assumptions:**
- Record size: ~300 bytes (JSON with timestamp + three limits)
- Rate limit: 30 sec → max 120 records/hour per window

**Usage scenarios:**

| Scenario | Description | Hours-windows/week | Records/week | Week | Month | Year |
|----------|-------------|-------------------|--------------|------|-------|------|
| Casual | 1-2h weekdays, 5h weekends, 1 window | ~15 | 1,800 | 540 KB | 2.2 MB | 26 MB |
| Regular dev | 4-5h work + pet project, 1-2 windows | ~43 | 5,160 | 1.5 MB | 6 MB | 78 MB |
| Advanced | 8h in 2-3 windows + pet project | ~150 | 18,000 | 5.4 MB | 22 MB | 280 MB |
| Extreme | 24/7, 4+ windows | ~670 | 80,640 | 24 MB | 100 MB | 1.2 GB |

**Target scenario** (between regular and advanced):
- ~95 hours-windows/week
- ~11,400 records/week
- 3.4 MB/week, 14 MB/month, 170 MB/year

**Retention:** 90 days covers seasonal patterns, caps storage at ~42 MB for target scenario.
