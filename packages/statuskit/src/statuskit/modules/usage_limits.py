"""Usage limits module for statuskit."""

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

HOURS_PER_DAY = 24
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/api/oauth/usage"
API_TIMEOUT = 3.0
CACHE_FILENAME = "usage_limits.json"
LOCK_FILENAME = "usage_limits.lock"


@dataclass
class UsageLimit:
    """Single usage limit with utilization percentage and reset time."""

    utilization: float  # 0-100
    resets_at: datetime


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
        return UsageLimit(
            utilization=data["utilization"],
            resets_at=datetime.fromisoformat(data["resets_at"]),
        )

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
    """Cache for usage data with TTL and rate limiting."""

    def __init__(
        self,
        cache_dir: Path,
        ttl: int = 60,
        rate_limit: int = 30,
    ):
        """Initialize cache.

        Args:
            cache_dir: Directory for cache files
            ttl: Time-to-live in seconds
            rate_limit: Minimum seconds between API fetches
        """
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.rate_limit = rate_limit
        self.cache_file = cache_dir / CACHE_FILENAME
        self.lock_file = cache_dir / LOCK_FILENAME

    def load(self) -> UsageData | None:
        """Load cached data if valid.

        Returns:
            UsageData or None if cache invalid/expired
        """
        try:
            if not self.cache_file.exists():
                return None

            data = json.loads(self.cache_file.read_text())
            fetched_at = datetime.fromisoformat(data["fetched_at"])

            # Check TTL
            age = (datetime.now(UTC) - fetched_at).total_seconds()
            if age > self.ttl:
                return None

            # Parse cached data
            def parse_limit(d: dict | None) -> UsageLimit | None:
                if d is None:
                    return None
                return UsageLimit(
                    utilization=d["utilization"],
                    resets_at=datetime.fromisoformat(d["resets_at"]),
                )

            return UsageData(
                session=parse_limit(data["data"].get("session")),
                weekly=parse_limit(data["data"].get("weekly")),
                sonnet=parse_limit(data["data"].get("sonnet")),
                fetched_at=fetched_at,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def save(self, data: UsageData) -> None:
        """Save data to cache.

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
                    "resets_at": limit.resets_at.isoformat(),
                }

            cache_data = {
                "data": {
                    "session": serialize_limit(data.session),
                    "weekly": serialize_limit(data.weekly),
                    "sonnet": serialize_limit(data.sonnet),
                },
                "fetched_at": data.fetched_at.isoformat(),
            }
            self.cache_file.write_text(json.dumps(cache_data))
        except OSError:
            pass

    def can_fetch(self) -> bool:
        """Check if API fetch is allowed (rate limiting).

        Returns:
            True if fetch allowed
        """
        try:
            if not self.lock_file.exists():
                return True
            last_fetch = float(self.lock_file.read_text())
            return (time.time() - last_fetch) >= self.rate_limit
        except (ValueError, OSError):
            return True

    def mark_fetched(self) -> None:
        """Mark that an API fetch was performed."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(str(time.time()))
        except OSError:
            pass
