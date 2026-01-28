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

    temp_path.replace(self.cache_file)  # atomic on POSIX and Windows
```

This prevents partial reads during concurrent access. Works on POSIX and Windows.

## Files to Change

- `packages/statuskit/src/statuskit/modules/usage_limits.py`
  - `UsageCache.load()` — remove TTL check
  - `UsageCache.save()` — atomic write
  - `UsageCache.can_fetch()` — read from cache file
  - Remove `mark_fetched()` — merged into save
  - Remove lock file handling
  - `UsageLimitsModule._get_usage_data()` — new logic

