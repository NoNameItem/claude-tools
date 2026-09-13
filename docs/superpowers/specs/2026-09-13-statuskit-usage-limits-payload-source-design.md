# StatusKit usage_limits: payload as the primary source, API only for per-model rows

**Date:** 2026-09-13
**Task:** claude-tools-5dl.24
**Module:** `packages/statuskit/src/statuskit/modules/usage_limits.py`, `packages/statuskit/src/statuskit/core/models.py`

## Problem

The `usage_limits` module gets every number from the undocumented
`GET https://api.anthropic.com/api/oauth/usage` endpoint, polled from every statusline render
with a shared 60 s cache. On 2026-09-13 the endpoint answered `429 rate_limit_error` for a
full hour while the module silently rendered a cache that was 40 minutes old
(`Session: 0% (—)` against a real 28% → 46%). Three defects combined:

1. **No staleness indication.** A failed fetch falls back to the cache with no visible mark,
   so plausible-looking but frozen numbers hide the outage.
2. **No backoff.** The 429 carries `Retry-After` (observed: 1198 s), but the module treats it
   like any other network error and keeps retrying every `cache_ttl`.
3. **Thundering herd.** There is no cross-process coordination (the `usage_limits.lock` file in
   the cache dir is a leftover from an old version). With N open sessions, every render in any
   session fetches as soon as `last_attempt_at` is older than the TTL, until the first one
   saves — several requests per second once a minute instead of one per minute. This is the
   most likely trigger of the 429.

## Findings that shape the design

- **Claude Code's statusline JSON now carries usage limits.** Since v2.1.2xx the payload has a
  documented optional `rate_limits` block
  (https://code.claude.com/docs/en/statusline — "Full JSON schema"):

  ```json
  "rate_limits": {
    "five_hour": { "used_percentage": 46, "resets_at": 1757809800 },
    "seven_day": { "used_percentage": 15, "resets_at": 1758000000 },
    "spend_limit": { "used_percentage": 0, "resets_at": 1758000000 }
  }
  ```

  `resets_at` is Unix epoch **seconds**. The block is present only for subscribers (or behind a
  spend-limited gateway), only after the first API response of the session, and each window is
  independently optional. Claude Code fills it from the `anthropic-ratelimit-unified-5h/7d-*`
  response headers — no network call, updated on every response, never rate-limited.
- **Per-model windows are not in the payload** and no supported API exposes them (Admin usage
  report needs an org admin key; Agent SDK exposes nothing; `/usage` has no JSON form). The
  only source for the `Current week (Fable)` row remains `/api/oauth/usage`, which Claude Code
  itself calls on demand (5 s timeout, no periodic polling, no special 429 handling).
- **The 429 window is fixed, not sliding.** Two probes 18 minutes apart (`Retry-After: 1198`
  and `92`) pointed at the same deadline while the module kept hammering; the deadline did not
  move and the endpoint returned 200 exactly at it. Block length was ~60 minutes. The budget
  that triggers it is unknown.

## Design

### Source split

| Rows | Source | Freshness |
|---|---|---|
| `Session` (5h overall), `Weekly` (7d overall) | statusline payload `rate_limits` | live, every render |
| Per-model rows (`Fable`, `Fable·cli`, …) | `/api/oauth/usage`, cached | up to `cache_ttl` |

The endpoint's own `session` / `weekly_all` values are still parsed and persisted (the parser
does not change), but they are no longer rendered: the overall rows come from the payload.
`spend_limit` is ignored.

### Payload rows and their cache

`StatusInput` gains `rate_limits: RateLimits | None`, where

```python
@dataclass
class RateLimitWindow:
    used_percentage: float
    resets_at: datetime | None   # from epoch seconds, UTC

@dataclass
class RateLimits:
    five_hour: RateLimitWindow | None
    seven_day: RateLimitWindow | None
```

Parsing is tolerant: missing block → `None`; a window whose `used_percentage` is not a finite
number is dropped; a missing/non-numeric `resets_at` becomes `None`; unknown keys are ignored.

The values are account-level, not session-level, so the last value seen by any session is
correct for a new one. On every render where the payload carries the block, the module stores
it in the cache as `payload` with `payload_seen_at = now`. On a render without the block
(session start, before the first API response) it renders the cached windows with an age suffix
(see "Staleness"). With neither payload nor cached payload, the `Session` / `Weekly` rows are not
rendered at all; per-model rows (if any) render at the top level, as the renderer already does
when a group has no overall row.

### Endpoint fetch: claim, TTL, backoff

`cache_ttl` default becomes **120 s** (was 60). The cache file gains `retry_after_until`
(ISO timestamp, absent when no backoff is active) next to `fetched_at` / `last_attempt_at`.

Decision on each render:

1. No token → cache only.
2. `now < retry_after_until` → cache only (debug: `Backing off until <t>`).
3. `now - last_attempt_at < cache_ttl` → cache only (debug: `Rate limited, using cache`).
4. Otherwise **claim first**: write `last_attempt_at = now` to the cache atomically (existing
   temp-file + `replace`), *then* fetch. Any other process rendering in the meantime sees the
   fresh stamp and takes branch 3. A crashed process costs at most one TTL of silence.

Fetch outcomes (`fetch_usage_api` returns a small result type instead of `UsageData | None`):

| Outcome | Persist | Debug message |
|---|---|---|
| 200, limits parsed | groups, `fetched_at = now`, clear `retry_after_until` | — |
| 200, nothing parsed | nothing beyond the claim | `Fetched OK but parsed no limits — API format may have changed` (unchanged) |
| 429 | `retry_after_until = now + Retry-After` (300 s when the header is missing or unparseable) | `HTTP 429, backing off for <n>s` |
| other HTTP error | nothing beyond the claim | `HTTP <code>, using cache` |
| timeout / URLError / JSON error | nothing beyond the claim | `<timeout|network error|bad JSON>, using cache` |

`urllib` raises `HTTPError` (a `URLError` subclass) for non-2xx: the handler must catch it
first, read `.code` and `.headers.get("Retry-After")`, and only then fall through to the generic
`URLError` branch.

### Staleness

A row rendered from the cache is **stale** when its source has failed to refresh:

- per-model rows: the last endpoint attempt failed, i.e. `fetched_at < last_attempt_at`
  (this covers an active `retry_after_until` window, since the claim advanced
  `last_attempt_at` without a successful fetch);
- payload rows: the current payload has no `rate_limits` and the rows come from the cached
  block.

Stale rows get a dark `(<age> ago)` suffix after the reset time, where age is
`now - fetched_at` (per-model) or `now - payload_seen_at` (payload rows), formatted with the
existing `format_remaining_time` (`40m`, `1h 5m`). Both render modes carry it:

```
Usage:
├ Session: 46% (3h 39m)
└ Weekly:  15% (Wed 08:00)
  └ Fable: 25% (Wed 08:00) (40m ago)

Usage: 5h 46% (3h 39m) | 7d 15% (Wed 08:00) | Fable 25% (Wed 08:00) (40m ago)
```

Rows from the live payload never carry the suffix. Cache-backed rows inside a successful TTL
window are not stale and carry no suffix either. There is no config switch for the suffix.

Colour of a stale row is computed as today from its utilization and reset time; the suffix is
the only marker.

### Cache file layout

```json
{
  "data": { "groups": [ … ] },
  "fetched_at": "…",
  "last_attempt_at": "…",
  "retry_after_until": "…",
  "payload": {
    "five_hour": { "used_percentage": 46.0, "resets_at": "…" },
    "seven_day": { "used_percentage": 15.0, "resets_at": "…" }
  },
  "payload_seen_at": "…"
}
```

`retry_after_until`, `payload`, `payload_seen_at` are optional; a cache written by the previous
version loads unchanged (no `payload` → no cached payload rows; no `retry_after_until` → no
backoff). Malformed values in the new keys are ignored the same way the existing loader ignores
malformed limits: timestamps that fail to parse are treated as absent.

### Out of scope

- The nested per-model row losing its indentation in the real statusline
  (claude-tools-5dl.23, statusline strips leading spaces) — separate bug, separate fix.
- `spend_limit` rendering.
- Any change to the endpoint response parser (`limits` array / legacy keys).

## Files

| File | Change |
|---|---|
| `packages/statuskit/src/statuskit/core/models.py` | `RateLimitWindow`, `RateLimits`, `StatusInput.rate_limits` + parsing |
| `packages/statuskit/src/statuskit/modules/usage_limits.py` | fetch result type with HTTP status / Retry-After; claim-before-fetch; `retry_after_until`; payload cache; source split in `_visible_groups`; stale suffix in `_format_limit`; `cache_ttl` default 120; debug messages |
| `packages/statuskit/tests/test_models.py` | payload parsing |
| `packages/statuskit/tests/test_usage_limits.py` | everything below |
| `packages/statuskit/README.md` | source split, staleness suffix, `cache_ttl` default |
| `packages/statuskit/src/statuskit/setup/config.py` | `# cache_ttl = 120` in the generated template |

## Testing (TDD, one failing test per step)

1. `StatusInput.from_dict`: full block; missing block; one window missing; non-finite
   `used_percentage` dropped; `resets_at` epoch → aware UTC datetime; non-numeric `resets_at`
   → `None`.
2. Fetch: 429 with `Retry-After: 1198` persists `retry_after_until = now + 1198 s`; 429
   without the header → 300 s; 401/5xx → cache untouched except the claim; timeout → same;
   200 clears `retry_after_until`.
3. Backoff: with `retry_after_until` in the future the API is not called; once it passes and
   the TTL has elapsed, it is.
4. Claim: the cache stamp is written before the fetch (a second module instance created between
   claim and response does not call the API); the claim survives a fetch that raises.
5. Source split: with payload `rate_limits`, `Session` / `Weekly` come from the payload even
   when the cache holds different numbers; per-model rows come from the cache.
6. Payload cache: a render with the block writes `payload` / `payload_seen_at`; a render without
   it renders the cached windows with `(<age> ago)`; with no cached payload the overall rows are
   absent and per-model rows render at the top level.
7. Staleness: per-model rows get the suffix only when `fetched_at < last_attempt_at`; both
   render modes; suffix absent inside a successful TTL window.
8. `cache_ttl` default is 120.
9. Debug messages carry the HTTP status / error class.
