"""Usage limits module for statuskit."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

from termcolor import colored

from statuskit.modules.base import BaseModule

if TYPE_CHECKING:
    from statuskit.core.models import RenderContext

HOURS_PER_DAY = 24
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_TIMEOUT = 3.0
CACHE_FILENAME = "usage_limits.json"


@dataclass
class UsageLimit:
    """Single usage limit with utilization percentage and reset time."""

    utilization: float  # 0-100
    resets_at: datetime | None  # None when limit not yet used or API issue


@dataclass
class UsageData:
    """Container for all usage limits."""

    session: UsageLimit | None  # five_hour
    weekly: UsageLimit | None  # seven_day
    sonnet: UsageLimit | None  # seven_day_sonnet
    fetched_at: datetime


def parse_api_response(response: dict) -> UsageData:
    """Parse API response into UsageData.

    Args:
        response: Raw API response dict

    Returns:
        UsageData with parsed limits
    """

    def parse_limit(data: dict | None) -> UsageLimit | None:
        if data is None:
            return None
        utilization = data.get("utilization")
        if utilization is None:
            return None
        resets_at_str = data.get("resets_at")
        resets_at = datetime.fromisoformat(resets_at_str) if resets_at_str else None
        return UsageLimit(utilization=utilization, resets_at=resets_at)

    return UsageData(
        session=parse_limit(response.get("five_hour")),
        weekly=parse_limit(response.get("seven_day")),
        sonnet=parse_limit(response.get("seven_day_sonnet")),
        fetched_at=datetime.now(UTC),
    )


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
        """Load cached data.

        Returns:
            UsageData or None if cache doesn't exist or is corrupted
        """
        try:
            if not self.cache_file.exists():
                return None

            data = json.loads(self.cache_file.read_text())
            fetched_at = datetime.fromisoformat(data["fetched_at"])

            def parse_limit(d: dict | None) -> UsageLimit | None:
                if d is None:
                    return None
                utilization = d.get("utilization")
                if utilization is None:
                    return None
                resets_at_str = d.get("resets_at")
                resets_at = datetime.fromisoformat(resets_at_str) if resets_at_str else None
                return UsageLimit(utilization=utilization, resets_at=resets_at)

            return UsageData(
                session=parse_limit(data["data"].get("session")),
                weekly=parse_limit(data["data"].get("weekly")),
                sonnet=parse_limit(data["data"].get("sonnet")),
                fetched_at=fetched_at,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def save(self, data: UsageData) -> None:
        """Save data to cache atomically.

        Uses temp file + rename for atomic writes to prevent
        race conditions with concurrent reads.

        Args:
            data: UsageData to cache
        """
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            def serialize_limit(limit: UsageLimit | None) -> dict | None:
                if limit is None:
                    return None
                return {
                    "utilization": limit.utilization,
                    "resets_at": limit.resets_at.isoformat() if limit.resets_at else None,
                }

            cache_data = {
                "data": {
                    "session": serialize_limit(data.session),
                    "weekly": serialize_limit(data.weekly),
                    "sonnet": serialize_limit(data.sonnet),
                },
                "fetched_at": data.fetched_at.isoformat(),
            }

            # Atomic write: temp file + rename
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.cache_dir,
                suffix=".tmp",
                delete=False,
            ) as f:
                f.write(json.dumps(cache_data))
                temp_path = Path(f.name)

            try:
                temp_path.replace(self.cache_file)
            except OSError:
                temp_path.unlink(missing_ok=True)
        except OSError:
            pass


# Window sizes in hours
FIVE_HOUR_WINDOW = 5.0
SEVEN_DAY_WINDOW = 7 * HOURS_PER_DAY


class UsageLimitsModule(BaseModule):
    """Module for displaying API usage limits."""

    name = "usage_limits"
    description = "API usage limits (5h session, 7d weekly, Sonnet-only)"

    def __init__(self, ctx: RenderContext, config: dict):
        """Initialize module with context and config."""
        super().__init__(ctx, config)
        self.show_session = config.get("show_session", True)
        self.show_weekly = config.get("show_weekly", True)
        self.show_sonnet = config.get("show_sonnet", False)
        self.show_reset_time = config.get("show_reset_time", True)
        self.multiline = config.get("multiline", True)
        self.show_progress_bar = config.get("show_progress_bar", False)
        self.bar_width = config.get("bar_width", 10)
        self.session_time_format = config.get("session_time_format", "remaining")
        self.weekly_time_format = config.get("weekly_time_format", "reset_at")
        self.sonnet_time_format = config.get("sonnet_time_format", "reset_at")

        # Initialize cache if cache_dir available
        self.cache = None
        if ctx.cache_dir:
            self.cache = UsageCache(cache_dir=ctx.cache_dir)

    def render(self) -> str | None:
        """Render usage limits display."""
        data = self._get_usage_data()

        parts: list[str] = []

        # Main output
        if data:
            if self.multiline:
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

        # Check rate limit using cached data (avoids second file read)
        if cached and self.cache:
            age = (datetime.now(UTC) - cached.fetched_at).total_seconds()
            if age < self.cache.rate_limit:
                self._debug_messages.append("Rate limited, using cache")
                return cached

        # Try to fetch fresh data
        new_data = fetch_usage_api(token)

        if not new_data:
            self._debug_messages.append("API failed, using cache")

        # Determine what to save and return
        data = new_data if new_data else cached

        # Save (updates fetched_at even on failure)
        if self.cache and data:
            self.cache.save(data)

        if not data:
            self._debug_messages.append("No data available")

        return data

    def _render_multiline(self, data: UsageData) -> str:
        """Render multiline format."""
        lines = [colored("Usage:", attrs=["dark"])]
        items = self._get_display_items(data)

        for i, (label, limit, window, time_fmt) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = colored("└" if is_last else "├", attrs=["dark"])
            line = self._format_line(label, limit, window, time_fmt)
            lines.append(f"{prefix} {line}")

        return "\n".join(lines)

    def _render_single_line(self, data: UsageData) -> str:
        """Render single-line format."""
        parts = []
        items = self._get_display_items(data)

        for label, limit, window, time_fmt in items:
            if "Session" in label:
                short_label = "5h"
            elif "Weekly" in label:
                short_label = "7d"
            else:
                short_label = "Sonnet"
            part = self._format_short(short_label, limit, window, time_fmt)
            parts.append(part)

        sep = colored(" | ", attrs=["dark"])
        return colored("Usage: ", attrs=["dark"]) + sep.join(parts)

    def _get_display_items(self, data: UsageData) -> list[tuple]:
        """Get list of (label, limit, window_hours, time_format) to display."""
        items = []
        if self.show_session and data.session:
            items.append(("Session:", data.session, FIVE_HOUR_WINDOW, self.session_time_format))
        if self.show_weekly and data.weekly:
            items.append(("Weekly:", data.weekly, SEVEN_DAY_WINDOW, self.weekly_time_format))
        if self.show_sonnet and data.sonnet:
            items.append(("Sonnet:", data.sonnet, SEVEN_DAY_WINDOW, self.sonnet_time_format))
        return items

    def _format_line(self, label: str, limit: UsageLimit, window: float, time_fmt: str) -> str:
        """Format a single line for multiline output."""
        # Handle missing resets_at (not yet used or API issue)
        if limit.resets_at is None:
            util_str = colored(f"{limit.utilization:.0f}%", attrs=["dark"])
            bar = ""
            if self.show_progress_bar:
                bar = f" {format_progress_bar(limit.utilization, self.bar_width)}"
            time_str = colored(" (—)", attrs=["dark"]) if self.show_reset_time else ""
            label_str = colored(f"{label:8}", attrs=["dark"])
            return f"{label_str}{bar} {util_str}{time_str}"

        now = datetime.now(UTC)
        remaining = (limit.resets_at - now).total_seconds() / 3600
        remaining = max(0, remaining)

        color = calculate_color(limit.utilization, remaining, window)
        util_str = colored(f"{limit.utilization:.0f}%", color)

        bar = ""
        if self.show_progress_bar:
            bar = f" {format_progress_bar(limit.utilization, self.bar_width)}"

        time_str = ""
        if self.show_reset_time:
            if time_fmt == "remaining":
                time_str = colored(f" ({format_remaining_time(remaining)})", attrs=["dark"])
            else:
                time_str = colored(f" ({format_reset_at(limit.resets_at)})", attrs=["dark"])

        label_str = colored(f"{label:8}", attrs=["dark"])
        return f"{label_str}{bar} {util_str}{time_str}"

    def _format_short(self, label: str, limit: UsageLimit, window: float, time_fmt: str) -> str:
        """Format a single item for single-line output."""
        # Handle missing resets_at (not yet used or API issue)
        if limit.resets_at is None:
            util_str = colored(f"{limit.utilization:.0f}%", attrs=["dark"])
            bar = ""
            if self.show_progress_bar:
                bar = f" {format_progress_bar(limit.utilization, self.bar_width // 2)}"
            time_str = colored(" (—)", attrs=["dark"]) if self.show_reset_time else ""
            label_str = colored(label, attrs=["dark"])
            return f"{label_str}{bar} {util_str}{time_str}"

        now = datetime.now(UTC)
        remaining = (limit.resets_at - now).total_seconds() / 3600
        remaining = max(0, remaining)

        color = calculate_color(limit.utilization, remaining, window)

        bar = ""
        if self.show_progress_bar:
            bar = f" {format_progress_bar(limit.utilization, self.bar_width // 2)}"

        util_str = colored(f"{limit.utilization:.0f}%", color)

        time_str = ""
        if self.show_reset_time:
            if time_fmt == "remaining":
                time_str = colored(f" ({format_remaining_time(remaining)})", attrs=["dark"])
            else:
                time_str = colored(f" ({format_reset_at(limit.resets_at)})", attrs=["dark"])

        label_str = colored(label, attrs=["dark"])
        return f"{label_str}{bar} {util_str}{time_str}"
