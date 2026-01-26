"""Test data factories for usage_limits module."""


def make_api_response(
    five_hour_util: float = 45.0,
    seven_day_util: float = 32.0,
    sonnet_util: float | None = 15.0,
    five_hour_reset: str = "2026-01-27T18:00:00+00:00",
    seven_day_reset: str = "2026-01-30T17:00:00+00:00",
) -> dict:
    """Create mock API response."""
    response = {
        "five_hour": {"utilization": five_hour_util, "resets_at": five_hour_reset},
        "seven_day": {"utilization": seven_day_util, "resets_at": seven_day_reset},
    }
    if sonnet_util is not None:
        response["seven_day_sonnet"] = {
            "utilization": sonnet_util,
            "resets_at": seven_day_reset,
        }
    return response
