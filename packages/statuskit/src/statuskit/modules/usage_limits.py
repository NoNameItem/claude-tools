"""Usage limits module for statuskit."""

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

HOURS_PER_DAY = 24
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"


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
