"""Usage limits module for statuskit."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

from termcolor import colored

from statuskit.core.schema import param, schema
from statuskit.modules.base import BaseModule

if TYPE_CHECKING:
    from statuskit.core.models import RenderContext

HOURS_PER_DAY = 24
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_TIMEOUT = 3.0
CACHE_FILENAME = "usage_limits.json"

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
    """

    label: str  # "Session" / "Weekly" / "Fable" / "Fable·cli"
    utilization: float  # 0-100
    resets_at: datetime | None  # None when not yet used or API issue
    model: str | None = None
    surface: str | None = None


@dataclass
class UsageGroup:
    """A window group (session / weekly) with an overall limit and per-model sub-limits."""

    key: str  # "session" | "weekly"
    window_hours: float  # 5.0 or 168.0 — used by the color heuristic
    overall: UsageLimit | None = None  # scope-less limit (session / weekly_all)
    models: list[UsageLimit] = field(default_factory=list)  # weekly_scoped per-model limits


@dataclass
class UsageData:
    """All usage groups plus fetch/attempt timestamps."""

    groups: list[UsageGroup]
    fetched_at: datetime
    last_attempt_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.last_attempt_at is None:
            self.last_attempt_at = self.fetched_at


def _as_dict(value: object) -> dict:
    """Return `value` when it is a dict, else an empty dict.

    API and cache payloads are untrusted: a key can hold a truthy non-dict (a model id string
    instead of a model object during an API shape change). A bare `x or {}` still lets that
    through, and the following `.get()` then raises AttributeError out of the parse path.
    """
    return value if isinstance(value, dict) else {}


def _parse_cache_datetime(value: object) -> datetime | None:
    """Parse an ISO timestamp from a cache payload, or None when missing/malformed."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _coerce_utilization(value: object) -> float | None:
    """Percent as a finite float, or None when the payload value is unusable.

    The single gate for BOTH the API and the cache parser — they were drifting apart, and a
    value rejected on one path but accepted on the other is how a bogus quota gets rendered.
    Rejects, specifically:
      * bool — `float(True)` is 1.0, so a malformed `"percent": true` would silently render 1%;
      * non-numerics (str/list/dict) — a numeric-looking string is still a shape change, and the
        renderer's `> 0` comparison and `:.0f` format assume a real number;
      * NaN / Infinity — json.loads() accepts those bare tokens, and they survive float() only
        to raise ValueError/OverflowError inside format_progress_bar's int().
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


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
    local_time = reset_time.astimezone()  # Convert to local timezone
    return local_time.strftime("%a %H:%M")


def format_progress_bar(utilization: float, width: int = 10) -> str:
    """Format utilization as a progress bar.

    Args:
        utilization: Usage percentage (0-100)
        width: Bar width in characters

    Returns:
        Formatted bar: "[████░░░░░░]"
    """
    filled = int(utilization / 100 * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _get_keychain_token() -> str | None:
    """Get token from macOS Keychain.

    Returns:
        Token string or None if not found
    """
    try:
        result = subprocess.run(  # noqa: S603
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


def fetch_usage_api(token: str) -> UsageData | None:
    """Fetch usage data from Anthropic API.

    Args:
        token: OAuth access token

    Returns:
        UsageData or None on error
    """
    try:
        request = Request(  # noqa: S310
            API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        with urlopen(request, timeout=API_TIMEOUT) as response:  # noqa: S310
            data = json.loads(response.read())
            return parse_api_response(data)
    except (TimeoutError, URLError, json.JSONDecodeError):
        pass
    return None


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

            def stamps_only() -> UsageData:
                return UsageData(groups=[], fetched_at=stamp, last_attempt_at=last_attempt_at)

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

            return UsageData(groups=groups, fetched_at=stamp, last_attempt_at=last_attempt_at)
        except (json.JSONDecodeError, KeyError, OSError, ValueError, TypeError, AttributeError):
            return None

    def save(self, data: UsageData) -> None:
        """Save data to cache atomically (temp file + rename)."""
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

            last_attempt_at = data.last_attempt_at or data.fetched_at
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
                "last_attempt_at": last_attempt_at.isoformat(),
            }

            with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, suffix=".tmp", delete=False) as f:
                f.write(json.dumps(cache_data))
                temp_path = Path(f.name)

            try:
                temp_path.replace(self.cache_file)
            except OSError:
                temp_path.unlink(missing_ok=True)
        except OSError:
            pass


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
    cache_ttl: int = param(60, "Minimum seconds between usage-API refetches")


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
        data = self._get_usage_data()

        parts: list[str] = []

        # Main output (only when there is something visible to show)
        if data and self._visible_groups(data):
            if self.params.multiline:
                parts.append(self._render_multiline(data))
            else:
                parts.append(self._render_single_line(data))

        # Debug output (appended to statusline)
        if self.debug and hasattr(self, "_debug_messages"):
            parts.extend(colored(f"[{self.name}] {msg}", "yellow") for msg in self._debug_messages)

        return "\n".join(parts) if parts else None

    def _get_usage_data(self) -> UsageData | None:
        """Get usage data using refresh-first pattern.

        Logic:
        1. Load existing cache (for fallback)
        2. If can fetch: try API, save result, return data
        3. Otherwise: return cached data
        """
        self._debug_messages: list[str] = []

        # Load cache for potential fallback
        cached = self.cache.load() if self.cache else None

        # Check if we can fetch
        token = get_token()
        if not token:
            self._debug_messages.append("No token, using cache")
            return cached

        # Check rate limit using cached data (avoids second file read).
        # Key off last_attempt_at, not fetched_at: a failed fetch leaves fetched_at stale but
        # must still throttle, otherwise every render re-hits the API and sustains a 429.
        if cached and cached.last_attempt_at and self.cache:
            age = (datetime.now(UTC) - cached.last_attempt_at).total_seconds()
            if age < self.cache.rate_limit:
                self._debug_messages.append("Rate limited, using cache")
                return cached

        # Try to fetch fresh data
        new_data = fetch_usage_api(token)

        # Determine what to return, and (separately) what to persist.
        to_save: UsageData | None
        if new_data and new_data.groups:
            data = new_data
            to_save = new_data
        elif new_data:
            # The request succeeded but nothing parsed — most likely the API changed shape.
            # RETURN the empty result rather than silently falling back to the cache: a stale but
            # plausible-looking statusline would hide the breakage and the user would never learn
            # statuskit needs updating. But do NOT persist it — writing an empty payload over the
            # last known-good cache would poison every LATER render that legitimately falls back
            # (no token / rate limited / API down), long after this hiccup passed.
            self._debug_messages.append("Fetched OK but parsed no limits — API format may have changed")
            data = new_data
            # With no cache to protect there is nothing to poison, and persisting the empty
            # payload is what keeps last_attempt_at advancing — otherwise the failing API would
            # be re-hit on every single render.
            to_save = cached if cached is not None else new_data
        else:
            self._debug_messages.append("API failed, using cache")
            data = cached
            to_save = cached

        # Advance the attempt clock on whatever we persist so the next render throttles instead of
        # hammering, while keeping fetched_at (true data age) untouched.
        if to_save is not None and to_save is not new_data:
            to_save.last_attempt_at = datetime.now(UTC)

        # Save so the advanced attempt clock (and any fresh data) persists across renders.
        if self.cache and to_save:
            self.cache.save(to_save)

        if not data:
            self._debug_messages.append("No data available")

        return data

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
        # Calculate color and time based on resets_at availability
        if limit.resets_at is None:
            # No reset time: dim color, placeholder for time
            color = None  # Will use attrs=["dark"]
            time_str = colored(" (—)", attrs=["dark"]) if self.params.show_reset_time else ""
        else:
            # Normalize naive datetime to UTC to avoid TypeError on subtraction
            resets_at = limit.resets_at
            if resets_at.tzinfo is None:
                resets_at = resets_at.replace(tzinfo=UTC)

            # Normal case: color based on utilization vs time
            now = datetime.now(UTC)
            remaining = max(0, (resets_at - now).total_seconds() / 3600)
            color = calculate_color(limit.utilization, remaining, window)
            time_str = ""
            if self.params.show_reset_time:
                if time_fmt == "remaining":
                    time_str = colored(f" ({format_remaining_time(remaining)})", attrs=["dark"])
                else:
                    time_str = colored(f" ({format_reset_at(resets_at)})", attrs=["dark"])

        # Format utilization with appropriate color
        if color is None:
            util_str = colored(f"{limit.utilization:.0f}%", attrs=["dark"])
        else:
            util_str = colored(f"{limit.utilization:.0f}%", color)

        bar = ""
        if self.params.show_progress_bar:
            bar = f" {format_progress_bar(limit.utilization, bar_width)}"

        return f"{label_str}{bar} {util_str}{time_str}"

    def _format_short(self, label: str, limit: UsageLimit, window: float, time_fmt: str) -> str:
        """Format a single item for single-line output."""
        label_str = colored(label, attrs=["dark"])
        return self._format_limit(label_str, limit, window, time_fmt, self.params.bar_width // 2)
