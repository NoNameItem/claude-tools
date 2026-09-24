"""Usage limits module for statuskit."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from termcolor import colored

from statuskit.core.models import RateLimits, RateLimitWindow, finite_float
from statuskit.core.schema import param, schema
from statuskit.modules.base import BaseModule

if TYPE_CHECKING:
    from statuskit.core.models import RenderContext

HOURS_PER_DAY = 24
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_TIMEOUT = 3.0
HTTP_TOO_MANY_REQUESTS = 429
RETRY_AFTER_FALLBACK = 300.0  # seconds to back off when a 429 carries no usable Retry-After
RETRY_AFTER_MAX = 3600.0  # cap on any 429 backoff: a huge Retry-After must not stall refreshes for years
CACHE_FILENAME = "usage_limits.json"
PAYLOAD_SAVE_INTERVAL = 60.0  # min seconds between cache writes of the statusline payload block
STALE_SUFFIX_FLOOR_SECONDS = 60.0  # never mark below this: format_remaining_time floors to "0m"

FIVE_HOUR_WINDOW = 5.0
SEVEN_DAY_WINDOW = 7 * HOURS_PER_DAY  # 168.0

# group key -> window hours / overall label / single-line short label / render order
_GROUP_WINDOWS = {"session": FIVE_HOUR_WINDOW, "weekly": float(SEVEN_DAY_WINDOW)}
_GROUP_LABELS = {"session": "Session", "weekly": "Weekly"}
_GROUP_SHORT = {"session": "5h", "weekly": "7d"}
_GROUP_ORDER = ("session", "weekly")
_SCOPE_SEPARATOR = "·"  # joins model and surface in a scoped row's label, e.g. "Fable·cli"


@dataclass
class UsageLimit:
    """A single displayable limit: a label, utilization %, and optional reset time.

    `model` / `surface` mirror the API's `scope` object and together identify a scoped row.
    A scoped limit is keyed by the PAIR, not by the model alone: the API can narrow a limit by
    model, by surface, or by both, and two rows differing only in `surface` are different
    quotas that must not collapse into one another. Both are None for a group's `overall`.

    `stale_seconds` is a render-time field set by the renderer when its source failed to refresh
    and the value is late for that source's refresh cycle.
    It is never parsed from the cache and never serialized.
    """

    label: str  # "Session" / "Weekly" / "Fable" / "Fable·cli"
    utilization: float  # 0-100
    resets_at: datetime | None  # None when not yet used or API issue
    model: str | None = None
    surface: str | None = None
    stale_seconds: float | None = None  # age of a cached value late for its source's refresh cycle


@dataclass
class UsageGroup:
    """A window group (session / weekly) with an overall limit and per-model sub-limits."""

    key: str  # "session" | "weekly"
    window_hours: float  # 5.0 or 168.0 — used by the color heuristic
    overall: UsageLimit | None = None  # scope-less limit (session / weekly_all)
    models: list[UsageLimit] = field(default_factory=list)  # weekly_scoped per-model limits


@dataclass
class FetchOutcome:
    """One usage-API call: the parsed data, or why it produced none.

    The caller needs more than "it failed": a 429 must start a backoff for exactly as long as the
    server asked, and the debug line must name the HTTP status so a 401 (token) is not mistaken
    for a 429 (rate limit) or a timeout (network).
    """

    data: UsageData | None = None
    status: int | None = None  # HTTP status when the server answered at all
    retry_after: float | None = None  # seconds, set only for a 429
    error: str | None = None  # short error class for the debug line


@dataclass
class UsageData:
    """All usage groups plus fetch/attempt timestamps.

    `last_attempt_at` has NO default derived from `fetched_at`: it means "an endpoint fetch was
    attempted at this instant", set only by `UsageCache.claim_attempt` and `_apply_outcome`. A
    `UsageData` built for another reason (e.g. `_persist_payload`'s cold-cache stand-in) must be
    able to say "no attempt has happened" — defaulting it to `fetched_at` would make that
    fabricated entry look like a completed attempt and wrongly throttle the next real one.
    """

    groups: list[UsageGroup]
    fetched_at: datetime
    last_attempt_at: datetime | None = None
    retry_after_until: datetime | None = None  # no request before this instant (from a 429)
    payload: RateLimits | None = None  # last `rate_limits` block seen in a statusline payload
    payload_seen_at: datetime | None = None  # when that block was seen


def _as_dict(value: object) -> dict:
    """Return `value` when it is a dict, else an empty dict.

    API and cache payloads are untrusted: a key can hold a truthy non-dict (a model id string
    instead of a model object during an API shape change). A bare `x or {}` still lets that
    through, and the following `.get()` then raises AttributeError out of the parse path.
    """
    return value if isinstance(value, dict) else {}


def _parse_cache_datetime(value: object) -> datetime | None:
    """Parse an ISO timestamp from a cache payload, or None when missing/malformed.

    An offset-less value (hand-edited or migrated cache) is read as UTC, the same as a naive
    `resets_at` at render time: every stamp parsed here is later compared with aware
    `datetime.now(UTC)`, and a naive one would raise TypeError there and take the module down.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _coerce_utilization(value: object) -> float | None:
    """Percent as a finite float, or None when the payload value is unusable.

    The single gate for BOTH the API and the cache parser — they were drifting apart, and a
    value rejected on one path but accepted on the other is how a bogus quota gets rendered.
    Rejects, specifically:
      * bool — `float(True)` is 1.0, so a malformed `"percent": true` would silently render 1%;
      * non-numerics (str/list/dict) — a numeric-looking string is still a shape change, and the
        renderer's `> 0` comparison and `:.0f` format assume a real number;
      * NaN / Infinity — json.loads() accepts those bare tokens, and they survive float() only
        to raise ValueError/OverflowError inside format_progress_bar's int();
      * ints too large for a float — json.loads() builds one from a long integer literal, and
        math.isfinite() raises OverflowError on it instead of returning False.
    """
    return finite_float(value)


def _deserialize_payload(value: object) -> RateLimits | None:
    """Rebuild the cached statusline payload block, or None when it is absent or unreadable."""
    if not isinstance(value, dict):
        return None

    def window(raw: object) -> RateLimitWindow | None:
        if not isinstance(raw, dict):
            return None
        used = _coerce_utilization(raw.get("used_percentage"))
        if used is None:
            return None
        resets_at = _parse_cache_datetime(raw.get("resets_at"))
        return RateLimitWindow(used_percentage=used, resets_at=resets_at)

    five_hour = window(value.get("five_hour"))
    seven_day = window(value.get("seven_day"))
    if five_hour is None and seven_day is None:
        return None
    return RateLimits(five_hour=five_hour, seven_day=seven_day)


def _serialize_payload(payload: RateLimits | None) -> dict | None:
    """Cache form of the payload block: percentages plus ISO reset times."""
    if payload is None:
        return None
    out: dict = {}
    for key, window in (("five_hour", payload.five_hour), ("seven_day", payload.seven_day)):
        if window is None:
            continue
        out[key] = {
            "used_percentage": window.used_percentage,
            "resets_at": window.resets_at.isoformat() if window.resets_at else None,
        }
    return out or None


def _payload_window(payload: RateLimits | None, group_key: str) -> RateLimitWindow | None:
    """The payload window backing a group's overall row."""
    if payload is None:
        return None
    return payload.five_hour if group_key == "session" else payload.seven_day


def _scope_label(model: str | None, surface: str | None) -> str | None:
    """Display label for a (model, surface) pair, or None when the pair is empty.

    The surface is shown verbatim rather than interpreted: the field is undocumented and always
    null in live responses today, so any mapping we invented would be a guess. Showing it raw
    keeps a narrower quota from masquerading as the model-wide one.
    """
    if model and surface:
        return f"{model}{_SCOPE_SEPARATOR}{surface}"
    return model or surface or None


def _parse_limit_fields(
    utilization: object,
    resets_at_str: str | None,
    label: str,
    model: str | None = None,
    surface: str | None = None,
) -> UsageLimit | None:
    """Build a UsageLimit from raw utilization/reset fields, or None if utilization is unusable."""
    util = _coerce_utilization(utilization)
    if util is None:
        return None
    resets_at = None
    if resets_at_str:
        try:
            resets_at = datetime.fromisoformat(resets_at_str)
        except (ValueError, TypeError):
            pass  # Malformed date string, treat as no reset time
    return UsageLimit(label=label, utilization=util, resets_at=resets_at, model=model, surface=surface)


def _parse_limits_array(limits: list) -> list[UsageGroup]:
    """Parse the self-describing `limits` array into ordered session/weekly groups."""
    groups: dict[str, UsageGroup] = {}

    def group_for(key: str | None) -> UsageGroup | None:
        if key not in _GROUP_WINDOWS:
            return None  # unknown window (e.g. future "monthly") — window unknown, skip
        if key not in groups:
            groups[key] = UsageGroup(key=key, window_hours=_GROUP_WINDOWS[key])
        return groups[key]

    seen_scopes: set[tuple[str, str | None, str | None]] = set()

    for item in limits:
        if not isinstance(item, dict):
            continue
        key = item.get("group")
        group = group_for(key)
        if group is None:
            continue
        scope = item.get("scope")
        if scope is None:
            # The group's scope-less limit. A scoped item must never land here, or the displayed
            # Session/Weekly percentage would silently be some narrower quota.
            limit = _parse_limit_fields(item.get("percent"), item.get("resets_at"), _GROUP_LABELS[key])
            if limit is not None:
                group.overall = limit
            continue
        if not isinstance(scope, dict):
            continue  # malformed scope — not the overall limit, and nothing to key a row by

        # A scoped row is identified by the (model, surface) PAIR. Either half may be absent;
        # both must be non-empty strings when present, since the label reaches `.casefold()` and
        # the row formatter.
        model_obj = scope.get("model")
        model = _as_dict(model_obj).get("display_name") if isinstance(model_obj, dict) else None
        surface = scope.get("surface")
        if not isinstance(model, str) or not model:
            model = None
        if not isinstance(surface, str) or not surface:
            surface = None
        label = _scope_label(model, surface)
        if label is None:
            continue  # scope object carrying neither a usable model nor a usable surface
        scope_key = (key, model, surface)
        if scope_key in seen_scopes:
            continue  # duplicate row for the same scope — keep the first, never double-count
        limit = _parse_limit_fields(item.get("percent"), item.get("resets_at"), label, model=model, surface=surface)
        if limit is not None:
            seen_scopes.add(scope_key)
            group.models.append(limit)

    ordered = [groups[k] for k in _GROUP_ORDER if k in groups]
    return [g for g in ordered if g.overall is not None or g.models]


def _parse_legacy(response: dict) -> list[UsageGroup]:
    """Fallback: build groups from legacy top-level keys (five_hour / seven_day / seven_day_sonnet)."""
    groups: list[UsageGroup] = []

    five_hour = _as_dict(response.get("five_hour"))
    session_overall = _parse_limit_fields(five_hour.get("utilization"), five_hour.get("resets_at"), "Session")
    if session_overall is not None:
        groups.append(UsageGroup("session", FIVE_HOUR_WINDOW, overall=session_overall))

    seven_day = _as_dict(response.get("seven_day"))
    weekly = UsageGroup("weekly", _GROUP_WINDOWS["weekly"])
    weekly.overall = _parse_limit_fields(seven_day.get("utilization"), seven_day.get("resets_at"), "Weekly")
    sonnet_raw = _as_dict(response.get("seven_day_sonnet"))
    sonnet = _parse_limit_fields(sonnet_raw.get("utilization"), sonnet_raw.get("resets_at"), "Sonnet", model="Sonnet")
    if sonnet is not None:
        weekly.models.append(sonnet)
    if weekly.overall is not None or weekly.models:
        groups.append(weekly)

    return groups


def _parse_retry_after(value: str | None) -> float:
    """Seconds to wait, from a 429's Retry-After header.

    Only the delta-seconds form is honoured; the HTTP-date form and anything unparseable or
    negative fall back to RETRY_AFTER_FALLBACK, which is never worse than hammering. The delay is
    capped at RETRY_AFTER_MAX: past a certain size `now + timedelta(...)` overflows and takes the
    whole module down, and well before that a finite but absurd value would stall refreshes for
    years. A server that really wants a longer pause answers the one capped retry with another 429.
    """
    if value:
        try:
            seconds = float(value.strip())
        except ValueError:
            return RETRY_AFTER_FALLBACK
        if math.isfinite(seconds) and seconds >= 0:
            return min(seconds, RETRY_AFTER_MAX)
    return RETRY_AFTER_FALLBACK


def _backoff_left(cached: UsageData | None, now: datetime) -> int | None:
    """Whole seconds left in an active 429 backoff, or None when none holds.

    Every deadline this module writes lies at most RETRY_AFTER_MAX past the moment it was written,
    so one further than that from `now` comes from a cache written before the cap existed, or from
    a corrupted file. Ignoring it costs one request; honouring it could stall refreshes for good.
    """
    until = cached.retry_after_until if cached else None
    if until is None or now >= until:
        return None
    left = (until - now).total_seconds()
    if left > RETRY_AFTER_MAX:
        return None
    return math.ceil(left)


def _late_age(age: float | None, refresh_interval: float) -> float | None:
    """`age` when a cached value is late for its source's refresh cycle, else None.

    The "(<age> ago)" suffix means "older than it should be", so it starts one refresh cycle out:
    inside the cycle the data is simply not due yet. Each source has its own cycle — `cache_ttl`
    for the endpoint, `PAYLOAD_SAVE_INTERVAL` for the payload block — and `cache_ttl` must not
    leak into payload rows, whose freshness it does not govern. The floor keeps the suffix clear
    of the range where format_remaining_time renders "0m", which reads as broken, not young.
    """
    if age is None or age < max(refresh_interval, STALE_SUFFIX_FLOOR_SECONDS):
        return None
    return age


def parse_api_response(response: object) -> UsageData:
    """Parse an API response into UsageData, preferring the `limits` array over legacy keys."""
    # Typed `object`, not `dict`: the payload comes straight from json.loads(), so a top-level
    # array or string is possible and would otherwise raise AttributeError out of the module.
    if not isinstance(response, dict):
        return UsageData(groups=[], fetched_at=datetime.now(UTC))
    limits = response.get("limits")
    if isinstance(limits, list) and limits:
        groups = _parse_limits_array(limits)
    else:
        groups = _parse_legacy(response)
    return UsageData(groups=groups, fetched_at=datetime.now(UTC))


def calculate_color(utilization: float, remaining_hours: float, window_hours: float) -> str:
    """Calculate color based on utilization vs elapsed time.

    Args:
        utilization: Current usage percentage (0-100)
        remaining_hours: Hours until reset
        window_hours: Total window size in hours

    Returns:
        Color name: "red", "yellow", or "green"
    """
    time_percent = (1 - remaining_hours / window_hours) * 100
    margin = 10  # fixed corridor

    if utilization > time_percent:
        return "red"
    if utilization > time_percent - margin:
        return "yellow"
    return "green"


def format_remaining_time(hours: float) -> str:
    """Format remaining time as human-readable string.

    Args:
        hours: Remaining hours until reset

    Returns:
        Formatted string: "45m", "2h 30m", or "5d 3h"
    """
    if hours < 1:
        minutes = int(hours * 60)
        return f"{minutes}m"
    if hours < HOURS_PER_DAY:
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h}h {m}m"
    days = int(hours / HOURS_PER_DAY)
    h = int(hours % HOURS_PER_DAY)
    return f"{days}d {h}h"


def format_reset_at(reset_time: datetime) -> str:
    """Format reset time as weekday and local time.

    Args:
        reset_time: UTC datetime of reset

    Returns:
        Formatted string: "Thu 17:00"
    """
    try:
        local_time = reset_time.astimezone()  # Convert to local timezone
    except (OverflowError, OSError, ValueError):
        # East of UTC a reset near datetime.max has no local time; show it in UTC instead.
        local_time = reset_time
    return local_time.strftime("%a %H:%M")


def format_progress_bar(utilization: float, width: int = 10) -> str:
    """Format utilization as a progress bar.

    Args:
        utilization: Usage percentage (0-100)
        width: Bar width in characters

    Returns:
        Formatted bar: "[████░░░░░░]"
    """
    # Clamp: the percent is untrusted, and an out-of-range value overflows or explodes the repeat count.
    filled = max(0, min(width, int(utilization / 100 * width)))
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _get_keychain_token() -> str | None:
    """Get token from macOS Keychain.

    Returns:
        Token string or None if not found
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv of the absolute /usr/bin/security path and constant args with no shell
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            # Keychain returns JSON with the token
            data = json.loads(result.stdout.strip())
            return data.get("claudeAiOauth", {}).get("accessToken")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def _get_file_token() -> str | None:
    """Get token from credentials file.

    Returns:
        Token string or None if not found
    """
    try:
        if CREDENTIALS_PATH.exists():
            data = json.loads(CREDENTIALS_PATH.read_text())
            return data.get("claudeAiOauth", {}).get("accessToken")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def get_token() -> str | None:
    """Get OAuth token from Keychain or credentials file.

    Returns:
        Token string or None if not found
    """
    return _get_keychain_token() or _get_file_token()


def fetch_usage_api(token: str) -> FetchOutcome:
    """Fetch usage data from the Anthropic OAuth usage endpoint.

    Args:
        token: OAuth access token

    Returns:
        FetchOutcome: parsed data on success, otherwise the status / retry hint / error class.
    """
    request = Request(  # noqa: S310 - URL is the constant https API_URL and never user-supplied
        API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urlopen(request, timeout=API_TIMEOUT) as response:  # noqa: S310 - opens the Request built above from API_URL
            payload = json.loads(response.read())
    except HTTPError as exc:
        # MUST precede URLError: HTTPError is a subclass, and only it carries the status and the
        # Retry-After header the backoff is built on.
        if exc.code == HTTP_TOO_MANY_REQUESTS:
            header = exc.headers.get("Retry-After") if exc.headers else None
            return FetchOutcome(status=exc.code, retry_after=_parse_retry_after(header))
        return FetchOutcome(status=exc.code)
    except TimeoutError:
        return FetchOutcome(error="timeout")
    except URLError:
        return FetchOutcome(error="network error")
    except json.JSONDecodeError:
        return FetchOutcome(error="bad JSON")
    return FetchOutcome(data=parse_api_response(payload))


class UsageCache:
    """Cache for usage data with rate limiting."""

    def __init__(
        self,
        cache_dir: Path,
        rate_limit: int = 30,
    ):
        """Initialize cache.

        Args:
            cache_dir: Directory for cache files
            rate_limit: Minimum seconds between API fetches
        """
        self.cache_dir = cache_dir
        self.rate_limit = rate_limit
        self.cache_file = cache_dir / CACHE_FILENAME
        # Set by `save()` on every call; `claim_attempt()`'s caller reads it to know whether the
        # attempt claim it just made actually reached disk.
        self.last_save_ok: bool = True

    def load(self) -> UsageData | None:
        """Load cached data, or None when the file is missing or carries no usable timestamp.

        A legacy (pre-groups) or otherwise unreadable payload does NOT yield None as long as a
        timestamp survives: the limits are dropped (empty `groups` renders nothing), but
        `last_attempt_at` is preserved. It is the only thing throttling the API — discarding it
        makes a failing API get re-hit on every single statusline render.
        """
        try:
            if not self.cache_file.exists():
                return None

            data = _as_dict(json.loads(self.cache_file.read_text()))
            fetched_at = _parse_cache_datetime(data.get("fetched_at"))
            last_attempt_at = _parse_cache_datetime(data.get("last_attempt_at"))
            # Independent keys: a missing/malformed `fetched_at` must not take a valid
            # `last_attempt_at` down with it.
            stamp = fetched_at if fetched_at is not None else last_attempt_at
            if stamp is None:
                return None  # no usable timestamp at all — nothing worth keeping

            retry_after_until = _parse_cache_datetime(data.get("retry_after_until"))
            payload_seen_at = _parse_cache_datetime(data.get("payload_seen_at"))
            payload = _deserialize_payload(data.get("payload"))
            if payload is None:
                payload_seen_at = None

            def stamps_only() -> UsageData:
                return UsageData(
                    groups=[],
                    fetched_at=stamp,
                    last_attempt_at=last_attempt_at,
                    retry_after_until=retry_after_until,
                    payload=payload,
                    payload_seen_at=payload_seen_at,
                )

            def deserialize_limit(d: dict | None) -> UsageLimit | None:
                if not isinstance(d, dict):
                    return None
                # `label` and `utilization` must be type-checked HERE, not left to the caller:
                # neither dict.get() nor the dataclass constructor raises on a wrong type, so a
                # corrupt cache value would sail past load()'s except block and only blow up at
                # render time (`label.casefold()`, `utilization > 0`, `f"{...:.0f}%"`).
                label = d.get("label", "")
                if not isinstance(label, str):
                    return None
                utilization = _coerce_utilization(d.get("utilization"))
                if utilization is None:
                    return None
                scope_model = d.get("model")
                scope_surface = d.get("surface")
                # Absent on caches written before scoped rows were keyed by the pair.
                if not isinstance(scope_model, str) or not scope_model:
                    scope_model = None
                if not isinstance(scope_surface, str) or not scope_surface:
                    scope_surface = None
                resets_at = None
                resets_at_str = d.get("resets_at")
                if resets_at_str:
                    try:
                        resets_at = datetime.fromisoformat(resets_at_str)
                    except (ValueError, TypeError):
                        pass
                return UsageLimit(
                    label=label,
                    utilization=utilization,
                    resets_at=resets_at,
                    model=scope_model,
                    surface=scope_surface,
                )

            groups_raw = _as_dict(data.get("data")).get("groups")
            if not isinstance(groups_raw, list):
                # Legacy {session,weekly,sonnet} cache, or a payload we cannot read: the limits
                # are a miss, but the timestamps still throttle the API.
                return stamps_only()

            try:
                groups: list[UsageGroup] = []
                for g in groups_raw:
                    if not isinstance(g, dict):
                        continue
                    key = g.get("key", "")
                    window = _GROUP_WINDOWS.get(key, _GROUP_WINDOWS["weekly"])
                    raw_models = g.get("models")
                    models = [
                        m
                        for m in (deserialize_limit(x) for x in (raw_models if isinstance(raw_models, list) else []))
                        if m is not None
                    ]
                    groups.append(
                        UsageGroup(
                            key=key, window_hours=window, overall=deserialize_limit(g.get("overall")), models=models
                        )
                    )
            except (ValueError, TypeError, AttributeError):
                return stamps_only()  # malformed group payload — keep the throttle timestamps

            return UsageData(
                groups=groups,
                fetched_at=stamp,
                last_attempt_at=last_attempt_at,
                retry_after_until=retry_after_until,
                payload=payload,
                payload_seen_at=payload_seen_at,
            )
        except (json.JSONDecodeError, KeyError, OSError, ValueError, TypeError, AttributeError):
            return None

    def save(self, data: UsageData) -> None:
        """Save data to cache atomically (temp file + rename).

        Sets `last_save_ok` so a caller that cares (`claim_attempt`'s caller, via the attribute)
        can tell a silently swallowed write failure from a normal save — a failed write here means
        the attempt claim never reached disk, and the thundering-herd protection it exists for
        comes back unnoticed.
        """
        self.last_save_ok = True
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            def serialize_limit(limit: UsageLimit | None) -> dict | None:
                if limit is None:
                    return None
                return {
                    "label": limit.label,
                    "utilization": limit.utilization,
                    "model": limit.model,
                    "surface": limit.surface,
                    "resets_at": limit.resets_at.isoformat() if limit.resets_at else None,
                }

            cache_data = {
                "data": {
                    "groups": [
                        {
                            "key": g.key,
                            "overall": serialize_limit(g.overall),
                            "models": [serialize_limit(m) for m in g.models],
                        }
                        for g in data.groups
                    ],
                },
                "fetched_at": data.fetched_at.isoformat(),
            }

            # No fallback to `fetched_at`: an unset `last_attempt_at` means no attempt was ever
            # made, and writing the key anyway would make a fabricated entry (a payload-only
            # write on a cold cache) look like a completed attempt on the next load.
            if data.last_attempt_at is not None:
                cache_data["last_attempt_at"] = data.last_attempt_at.isoformat()

            if data.retry_after_until is not None:
                cache_data["retry_after_until"] = data.retry_after_until.isoformat()
            serialized_payload = _serialize_payload(data.payload)
            if serialized_payload is not None:
                cache_data["payload"] = serialized_payload
                seen = data.payload_seen_at or data.fetched_at
                cache_data["payload_seen_at"] = seen.isoformat()

            with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, suffix=".tmp", delete=False) as f:
                f.write(json.dumps(cache_data))
                temp_path = Path(f.name)

            try:
                temp_path.replace(self.cache_file)
            except OSError:
                temp_path.unlink(missing_ok=True)
                self.last_save_ok = False
        except OSError:
            self.last_save_ok = False

    def claim_attempt(self, cached: UsageData | None) -> UsageData:
        """Stamp an attempt as starting now and persist it, before the request goes out.

        Several Claude Code sessions render the same statusline against the same cache file. With
        the stamp written only after the response, every session whose render lands in the gap
        fires its own request — a burst per TTL instead of one call. Claiming first costs one
        atomic write and makes the other sessions fall into the TTL branch. A process that dies
        mid-request costs at most one TTL of staleness.
        """
        now = datetime.now(UTC)
        claimed = cached if cached is not None else UsageData(groups=[], fetched_at=now)
        claimed.last_attempt_at = now
        self.save(claimed)
        return claimed


# Shared by the three *_time_format fields below (same choices, same examples).
_TIME_FORMAT_CHOICES = {
    "remaining": "time left until reset — e.g. `2h 30m`",
    "reset_at": "wall-clock reset time — e.g. `Thu 17:00`",
}


@schema
class UsageLimitsParams:
    show_session: bool = param(True, "Show 5-hour session limit")
    show_weekly: bool = param(True, "Show 7-day weekly limit")
    # Both match a bare model name OR a full model·surface label, symmetrically: `fable` covers
    # every Fable row including narrower scoped ones, `fable·cli` targets exactly that row. So a
    # bare name in always_show will also force-show a scoped Fable row the user never configured.
    models_always_show: list[str] = param(
        [],
        "Model (or model·surface) names to always show, even at 0%; a bare name covers its scoped rows",
        type_=list[str],
    )
    models_never_show: list[str] = param(
        [],
        "Model (or model·surface) names to never show; a bare name covers its scoped rows",
        type_=list[str],
    )
    show_reset_time: bool = param(True, "Show time until / when reset occurs")
    multiline: bool = param(True, "Multi-line output (one limit per line)")
    show_progress_bar: bool = param(False, "Show ASCII progress bar")
    bar_width: int = param(10, "Progress bar character width")
    session_time_format: str = param("remaining", "Session time display", choices=_TIME_FORMAT_CHOICES)
    weekly_time_format: str = param("reset_at", "Weekly time display", choices=_TIME_FORMAT_CHOICES)
    model_time_format: str = param("reset_at", "Per-model time display", choices=_TIME_FORMAT_CHOICES)
    cache_ttl: int = param(120, "Minimum seconds between usage-API refetches")


class UsageLimitsModule(BaseModule[UsageLimitsParams]):
    """Module for displaying API usage limits."""

    name = "usage_limits"
    description = "API usage limits (5h session, 7d weekly, per-model)"

    def __init__(self, ctx: RenderContext, raw_section: dict) -> None:
        """Initialize module: parse params, then set up the rate-limited cache."""
        super().__init__(ctx, raw_section)
        self.cache = UsageCache(cache_dir=ctx.cache_dir, rate_limit=self.params.cache_ttl) if ctx.cache_dir else None

    def render(self) -> str | None:
        """Render usage limits display."""
        display = self._display_data(self._get_usage_data())

        parts: list[str] = []

        if display and self._visible_groups(display):
            if self.params.multiline:
                parts.append(self._render_multiline(display))
            else:
                parts.append(self._render_single_line(display))

        if self.debug and hasattr(self, "_debug_messages"):
            parts.extend(colored(f"[{self.name}] {msg}", "yellow") for msg in self._debug_messages)

        return "\n".join(parts) if parts else None

    def _get_usage_data(self) -> UsageData | None:
        """Load cached usage data, refreshing it from the API when policy allows.

        Gates run cheapest first: an active 429 backoff, then the TTL. Past both, the attempt is
        claimed in the cache so sibling sessions stand down, and only then is the token looked up.
        On macOS that lookup is a ~16 ms Keychain subprocess: ahead of the claim it would widen the
        window in which sibling sessions all pass the TTL on the same stale stamp, and every render
        the TTL blocks would pay for it. A missing token therefore counts as a failed attempt, the
        same as a network error.
        """
        self._debug_messages: list[str] = []

        cached = self.cache.load() if self.cache else None
        cached = self._persist_payload(cached)

        now = datetime.now(UTC)
        backoff_left = _backoff_left(cached, now)
        if backoff_left is not None:
            self._debug_messages.append(f"Backing off after HTTP 429, {backoff_left}s left")
            return cached

        # Key off last_attempt_at, not fetched_at: a failed fetch leaves fetched_at stale but must
        # still throttle, otherwise every render re-hits the API and sustains a 429.
        if cached and cached.last_attempt_at and self.cache:
            age = (now - cached.last_attempt_at).total_seconds()
            if age < self.cache.rate_limit:
                self._debug_messages.append("Rate limited, using cache")
                return cached

        if self.cache:
            cached = self.cache.claim_attempt(cached)
            if not self.cache.last_save_ok:
                self._debug_messages.append("Could not write the attempt claim; sibling sessions may all refetch")

        token = get_token()
        if not token:
            self._debug_messages.append("No token, using cache")
            return cached

        outcome = fetch_usage_api(token)
        # Fold the outcome into the cache as it is now, not into the snapshot loaded before the
        # request: the request can take up to API_TIMEOUT, and saving that snapshot would roll back
        # whatever sibling sessions persisted meanwhile (a fresher payload, a 429 backoff). Our own
        # snapshot is the fallback only when the re-load yields nothing at all.
        fresh = self.cache.load() if self.cache else None
        data, to_save = self._apply_outcome(outcome, fresh if fresh is not None else cached)

        if self.cache and to_save is not None:
            self.cache.save(to_save)
        if not data:
            self._debug_messages.append("No data available")
        return data

    def _apply_outcome(
        self, outcome: FetchOutcome, cached: UsageData | None
    ) -> tuple[UsageData | None, UsageData | None]:
        """Fold one fetch outcome into (what to render, what to persist)."""
        now = datetime.now(UTC)
        new_data = outcome.data

        if new_data and new_data.groups:
            # Both stamps describe THIS attempt: `model_age` (in `_display_data`) measures staleness
            # as `fetched_at < last_attempt_at`, and a successful fetch must make that false, not
            # merely close to false — else the age keeps growing from a `fetched_at` set moments
            # earlier inside `parse_api_response`, and every per-model row carries a permanent
            # "(0m ago)" that only grows.
            new_data.fetched_at = now
            new_data.last_attempt_at = now
            # Carry the payload block across a successful endpoint fetch — it belongs to the other
            # source and a refresh here must not wipe it. retry_after_until stays at its default
            # None, which is exactly how a success clears an earlier backoff.
            if cached is not None:
                new_data.payload = cached.payload
                new_data.payload_seen_at = cached.payload_seen_at
            return new_data, new_data

        if new_data is not None:
            # The request succeeded but nothing parsed — most likely the API changed shape. RETURN
            # the empty result rather than silently falling back to the cache: a stale but
            # plausible-looking statusline would hide the breakage. But do NOT persist it over the
            # last known-good cache, which every later fallback render depends on.
            self._debug_messages.append("Fetched OK but parsed no limits — API format may have changed")
            # Carry the payload block too — it belongs to the other source, and dropping it here
            # would make the whole Usage block vanish (Session/Weekly included) for as long as the
            # endpoint keeps answering 200 with an unparseable body, even though the payload itself
            # never stopped arriving.
            if cached is not None:
                new_data.payload = cached.payload
                new_data.payload_seen_at = cached.payload_seen_at
            # `cached`, not `cached if cached is not None else new_data`: by this point `_get_usage_data`
            # has always claimed the attempt first, so `cached` is non-None whenever `self.cache`
            # exists; when it doesn't, the caller discards `to_save` anyway.
            return new_data, cached

        if outcome.retry_after is not None:
            self._debug_messages.append(f"HTTP {outcome.status}, backing off for {int(outcome.retry_after)}s")
            if cached is not None:
                cached.retry_after_until = now + timedelta(seconds=outcome.retry_after)
        elif outcome.status is not None:
            self._debug_messages.append(f"HTTP {outcome.status}, using cache")
        else:
            self._debug_messages.append(f"{outcome.error or 'API failed'}, using cache")
        return cached, cached

    def _live_payload(self) -> RateLimits | None:
        """The `rate_limits` block of THIS render's statusline payload, when Claude Code sent one."""
        return self.data.rate_limits

    def _persist_payload(self, cached: UsageData | None) -> UsageData | None:
        """Store this render's payload limits in the cache, at most once per PAYLOAD_SAVE_INTERVAL.

        The limits are account-wide, not session-wide, so the last block seen by any session is
        correct for a session that has not made its first API call yet. Writing on every render
        would mean a file write per statusline repaint, hence the interval.
        """
        live = self._live_payload()
        if live is None or self.cache is None:
            return cached
        now = datetime.now(UTC)
        entry = cached if cached is not None else UsageData(groups=[], fetched_at=now)
        seen = entry.payload_seen_at
        if seen is not None and (now - seen).total_seconds() < PAYLOAD_SAVE_INTERVAL:
            return entry
        entry.payload = live
        entry.payload_seen_at = now
        self.cache.save(entry)
        return entry

    def _resolve_payload(self, data: UsageData | None, now: datetime) -> tuple[RateLimits | None, float | None]:
        """The payload to render from, plus its age in seconds when it comes from the cache."""
        live = self._live_payload()
        if live is not None:
            return live, None
        if data and data.payload is not None and data.payload_seen_at is not None:
            return data.payload, (now - data.payload_seen_at).total_seconds()
        return None, None

    def _display_data(self, data: UsageData | None) -> UsageData | None:
        """Merge the two sources into the groups to render.

        Overall rows come from the statusline payload (live, or the cached block). Per-model rows
        come from the API cache, which is the only source that has them.
        """
        now = datetime.now(UTC)
        payload, payload_age = self._resolve_payload(data, now)
        if payload is None and hasattr(self, "_debug_messages"):
            self._debug_messages.append(
                "No rate_limits in the statusline payload — Session/Weekly need a recent Claude Code"
            )

        # A per-model row is stale when the last refresh attempt did not produce data: the claim
        # advanced last_attempt_at while fetched_at stayed where the last success left it. An
        # active 429 backoff is covered by the same comparison.
        model_age: float | None = None
        if data and data.last_attempt_at and data.fetched_at < data.last_attempt_at:
            model_age = _late_age((now - data.fetched_at).total_seconds(), self.params.cache_ttl)

        payload_stale = _late_age(payload_age, PAYLOAD_SAVE_INTERVAL)
        groups: list[UsageGroup] = []
        for key in _GROUP_ORDER:
            window = _payload_window(payload, key)
            overall = (
                UsageLimit(
                    label=_GROUP_LABELS[key],
                    utilization=window.used_percentage,
                    resets_at=window.resets_at,
                    stale_seconds=payload_stale,
                )
                if window is not None
                else None
            )
            group_models = [m for g in (data.groups if data else []) if g.key == key for m in g.models]
            # Only copy when there is an age to stamp: the common path is fresh data, and a
            # per-row `replace` on every render allocates for nothing.
            models = group_models if model_age is None else [replace(m, stale_seconds=model_age) for m in group_models]
            if overall is not None or models:
                groups.append(UsageGroup(key=key, window_hours=_GROUP_WINDOWS[key], overall=overall, models=models))
        return UsageData(groups=groups, fetched_at=now) if groups else None

    def _visible_groups(self, data: UsageData) -> list[tuple[UsageGroup, UsageLimit | None, list[UsageLimit]]]:
        """For each group, return (group, overall-or-None-if-hidden, visible models)."""
        always = {n.casefold() for n in self.params.models_always_show}
        never = {n.casefold() for n in self.params.models_never_show}
        result: list[tuple[UsageGroup, UsageLimit | None, list[UsageLimit]]] = []
        for g in data.groups:
            show_overall = g.overall is not None and (
                (g.key == "session" and self.params.show_session) or (g.key == "weekly" and self.params.show_weekly)
            )
            visible_models = []
            for m in g.models:
                # Match the full label AND the bare model name, so an existing `fable` entry keeps
                # covering a narrower `Fable·cli` row; `fable·cli` targets just that one.
                names = {m.label.casefold()}
                if m.model:
                    names.add(m.model.casefold())
                if names & never:
                    continue
                if names & always or m.utilization > 0 or m.resets_at is not None:
                    visible_models.append(m)
            if show_overall or visible_models:
                result.append((g, g.overall if show_overall else None, visible_models))
        return result

    def _time_format_for(self, group_key: str, is_model: bool) -> str:
        if is_model:
            return self.params.model_time_format
        return self.params.session_time_format if group_key == "session" else self.params.weekly_time_format

    def _label_width(self, groups: list[tuple[UsageGroup, UsageLimit | None, list[UsageLimit]]]) -> int:
        """Column width (including trailing colon) sized to the longest visible label."""
        labels: list[str] = []
        for _g, overall, models in groups:
            if overall is not None:
                labels.append(overall.label)
            labels.extend(m.label for m in models)
        return max((len(label) for label in labels), default=0) + 1

    def _render_multiline(self, data: UsageData) -> str:
        """Render nested multiline: models indented under their group's overall row."""
        groups = self._visible_groups(data)
        width = self._label_width(groups)
        lines = [colored("Usage:", attrs=["dark"])]

        for i, (g, overall, models) in enumerate(groups):
            is_last_top = i == len(groups) - 1
            if overall is not None:
                prefix = colored("└" if is_last_top else "├", attrs=["dark"])
                row = self._format_row(
                    overall.label,
                    overall,
                    g.window_hours,
                    self._time_format_for(g.key, False),
                    width,
                    self.params.bar_width,
                )
                lines.append(f"{prefix} {row}")
                for j, m in enumerate(models):
                    child = colored("└" if j == len(models) - 1 else "├", attrs=["dark"])
                    row = self._format_row(
                        m.label, m, g.window_hours, self.params.model_time_format, width, self.params.bar_width
                    )
                    lines.append(f"  {child} {row}")
            else:
                # No overall shown for this group — models render at the top level.
                for j, m in enumerate(models):
                    is_last = is_last_top and j == len(models) - 1
                    prefix = colored("└" if is_last else "├", attrs=["dark"])
                    row = self._format_row(
                        m.label, m, g.window_hours, self.params.model_time_format, width, self.params.bar_width
                    )
                    lines.append(f"{prefix} {row}")

        return "\n".join(lines)

    def _render_single_line(self, data: UsageData) -> str:
        """Render flat single-line: session, weekly, then each visible model."""
        parts: list[str] = []
        for g, overall, models in self._visible_groups(data):
            if overall is not None:
                short = _GROUP_SHORT.get(g.key, g.key)
                parts.append(self._format_short(short, overall, g.window_hours, self._time_format_for(g.key, False)))
            parts.extend(self._format_short(m.label, m, g.window_hours, self.params.model_time_format) for m in models)
        sep = colored(" | ", attrs=["dark"])
        return colored("Usage: ", attrs=["dark"]) + sep.join(parts)

    def _format_row(
        self, label: str, limit: UsageLimit, window: float, time_fmt: str, width: int, bar_width: int
    ) -> str:
        """Format one multiline row with a colon-suffixed, width-padded label."""
        label_str = colored(f"{label + ':':<{width}}", attrs=["dark"])
        return self._format_limit(label_str, limit, window, time_fmt, bar_width)

    def _format_limit(
        self,
        label_str: str,
        limit: UsageLimit,
        window: float,
        time_fmt: str,
        bar_width: int,
    ) -> str:
        """Format a single limit item.

        Args:
            label_str: Pre-formatted label string
            limit: Usage limit data
            window: Time window in hours
            time_fmt: Time format ("remaining" or "reset_at")
            bar_width: Width for progress bar
        """
        color, time_str = self._color_and_reset_time(limit, window, time_fmt)

        # Format utilization with appropriate color
        if color is None:
            util_str = colored(f"{limit.utilization:.0f}%", attrs=["dark"])
        else:
            util_str = colored(f"{limit.utilization:.0f}%", color)

        bar = ""
        if self.params.show_progress_bar:
            bar = f" {format_progress_bar(limit.utilization, bar_width)}"

        return f"{label_str}{bar} {util_str}{time_str}{self._stale_suffix(limit)}"

    def _color_and_reset_time(self, limit: UsageLimit, window: float, time_fmt: str) -> tuple[str | None, str]:
        """Pick the utilization color and the reset-time suffix for a single limit item.

        Returns:
            (color, time_str). color is None when the limit has no reset time: the
            utilization is then rendered dim instead of colored against the window.
        """
        if limit.resets_at is None:
            # No reset time: dim color, placeholder for time
            return None, colored(" (—)", attrs=["dark"]) if self.params.show_reset_time else ""

        # Normalize naive datetime to UTC to avoid TypeError on subtraction
        resets_at = limit.resets_at
        if resets_at.tzinfo is None:
            resets_at = resets_at.replace(tzinfo=UTC)

        # Normal case: color based on utilization vs time
        now = datetime.now(UTC)
        remaining = max(0, (resets_at - now).total_seconds() / 3600)
        color = calculate_color(limit.utilization, remaining, window)
        if not self.params.show_reset_time:
            return color, ""
        if time_fmt == "remaining":
            return color, colored(f" ({format_remaining_time(remaining)})", attrs=["dark"])
        return color, colored(f" ({format_reset_at(resets_at)})", attrs=["dark"])

    def _stale_suffix(self, limit: UsageLimit) -> str:
        """Format the "(<age> ago)" suffix of a cached value that is late for its source (see _late_age)."""
        if limit.stale_seconds is None:
            return ""
        return colored(f" ({format_remaining_time(limit.stale_seconds / 3600)} ago)", attrs=["dark"])

    def _format_short(self, label: str, limit: UsageLimit, window: float, time_fmt: str) -> str:
        """Format a single item for single-line output."""
        label_str = colored(label, attrs=["dark"])
        return self._format_limit(label_str, limit, window, time_fmt, self.params.bar_width // 2)
