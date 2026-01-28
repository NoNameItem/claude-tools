"""Test data factories for usage_limits module."""


def make_api_response(
    five_hour_util: float = 45.0,
    seven_day_util: float = 32.0,
    sonnet_util: float | None = 15.0,
    five_hour_reset: str = "2026-01-27T18:00:00+00:00",
    seven_day_reset: str = "2026-01-30T17:00:00+00:00",
    sonnet_reset: str | None = None,
) -> dict:
    """Create mock API response.

    Args:
        five_hour_util: Utilization for 5-hour session limit
        seven_day_util: Utilization for 7-day weekly limit
        sonnet_util: Utilization for Sonnet limit (None to omit limit entirely)
        five_hour_reset: Reset time for 5-hour limit
        seven_day_reset: Reset time for 7-day limit
        sonnet_reset: Reset time for Sonnet limit (None = not yet used, uses seven_day_reset if not specified)
    """
    response = {
        "five_hour": {"utilization": five_hour_util, "resets_at": five_hour_reset},
        "seven_day": {"utilization": seven_day_util, "resets_at": seven_day_reset},
    }
    if sonnet_util is not None:
        response["seven_day_sonnet"] = {
            "utilization": sonnet_util,
            # Use sonnet_reset if provided, otherwise default to seven_day_reset
            "resets_at": sonnet_reset if sonnet_reset is not None else seven_day_reset,
        }
    return response


def make_api_response_with_null_reset(
    five_hour_util: float = 45.0,
    seven_day_util: float = 32.0,
    sonnet_util: float = 0.0,
    five_hour_reset: str = "2026-01-27T18:00:00+00:00",
    seven_day_reset: str = "2026-01-30T17:00:00+00:00",
) -> dict:
    """Create mock API response with null resets_at for Sonnet (not yet used scenario)."""
    return {
        "five_hour": {"utilization": five_hour_util, "resets_at": five_hour_reset},
        "seven_day": {"utilization": seven_day_util, "resets_at": seven_day_reset},
        "seven_day_sonnet": {"utilization": sonnet_util, "resets_at": None},
    }
