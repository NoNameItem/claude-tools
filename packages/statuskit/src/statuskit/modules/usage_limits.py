"""Usage limits module for statuskit."""

from dataclasses import dataclass
from datetime import UTC, datetime


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
