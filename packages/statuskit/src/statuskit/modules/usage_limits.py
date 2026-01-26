"""Usage limits module for statuskit."""

from dataclasses import dataclass
from datetime import UTC, datetime

HOURS_PER_DAY = 24


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
