# Design: Commit Age Format Decomposition

**Task:** claude-tools-5dl.7
**Date:** 2026-01-27
**Status:** Draft

## Problem

Current `commit_age_format = "compact"` shows "69m" instead of decomposing into larger units like "1h 9m". The implementation only shortens unit names without converting values.

## Solution

Add time decomposition that breaks down minutes into days, hours, and minutes. Introduce three formats with different output styles.

## Formats

| Format | Description | Example (69 mins) |
|--------|-------------|-------------------|
| `raw` | Original git output | "69 minutes ago" |
| `relative` | Decomposed + full names + "ago" | "1 hour 9 minutes ago" |
| `compact` | Decomposed + short names | "1h 9m" |

**Default:** `relative`

**Configuration:**
```toml
[git]
commit_age_format = "compact"  # raw | relative | compact
```

## Decomposition Logic

**Units:** days (d), hours (h), minutes (m)

**Constants:**
- 1 day = 1440 minutes
- 1 hour = 60 minutes

**Algorithm:**
1. Parse git output → total minutes
2. Decompose: `days = total // 1440`, `hours = (total % 1440) // 60`, `mins = total % 60`
3. Show all non-zero units in order: d → h → m
4. If total < 1 minute → "just now"

**Examples:**

| Git output | Total mins | compact | relative |
|------------|-----------|---------|----------|
| "30 seconds ago" | 0 | just now | just now |
| "5 minutes ago" | 5 | 5m | 5 minutes ago |
| "69 minutes ago" | 69 | 1h 9m | 1 hour 9 minutes ago |
| "2 hours ago" | 120 | 2h | 2 hours ago |
| "26 hours ago" | 1560 | 1d 2h | 1 day 2 hours ago |
| "3 days ago" | 4320 | 3d | 3 days ago |

**Converting large units from git:**
- weeks → days × 7
- months → days × 30
- years → days × 365

## Implementation

**Parsing git output:**

```python
UNIT_TO_MINUTES = {
    "second": 0, "seconds": 0,
    "minute": 1, "minutes": 1,
    "hour": 60, "hours": 60,
    "day": 1440, "days": 1440,
    "week": 10080, "weeks": 10080,
    "month": 43200, "months": 43200,
    "year": 525600, "years": 525600,
}
```

**Code structure:**

Split `_format_commit_age` into:
1. `_parse_git_age(age_str) -> int` — parse string, return total minutes
2. `_decompose_minutes(total) -> tuple[int, int, int]` — return (days, hours, mins)
3. `_format_commit_age(age_str) -> str` — main method using the two above

## Testing

**Test scenarios:**

1. **Each format:**
   - raw: returns string as-is
   - relative: decomposition with full names
   - compact: decomposition with short names

2. **Decomposition:**
   - Minutes only: 5m / 5 minutes ago
   - Minutes → hours + minutes: 69m → 1h 9m
   - Hours → days + hours: 26h → 1d 2h
   - Full chain: 1501m → 1d 1h 1m

3. **Edge cases:**
   - < 1 minute → "just now"
   - Even values (60m → 1h, not 1h 0m)
   - Large units from git (weeks, months, years)

4. **Parsing:**
   - Invalid string → return as-is (fallback)

## Files to Change

- `packages/statuskit/src/statuskit/modules/git.py` — logic
- `packages/statuskit/tests/test_git_module.py` — tests

## Breaking Changes

Default `commit_age_format = "relative"` will now decompose time instead of returning raw git output. Users who want the old behavior should set `commit_age_format = "raw"`.
