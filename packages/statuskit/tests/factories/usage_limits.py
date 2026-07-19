"""Test data factories for usage_limits module."""

from __future__ import annotations


def _limit(kind: str, group: str, percent: float | None, resets_at: str | None, model: str | None = None) -> dict:
    """One entry of the API `limits` array. `model` set => weekly_scoped with a display_name."""
    scope = {"model": {"id": None, "display_name": model}, "surface": None} if model is not None else None
    return {
        "kind": kind,
        "group": group,
        "percent": percent,
        "severity": "normal",
        "resets_at": resets_at,
        "scope": scope,
        "is_active": kind == "session",
    }


def make_api_response(
    session_percent: float | None = 11.0,
    weekly_percent: float | None = 2.0,
    models: dict[str, tuple[float, str | None]] | None = None,
    session_reset: str | None = "2026-01-27T18:00:00+00:00",
    weekly_reset: str | None = "2026-01-30T17:00:00+00:00",
) -> dict:
    """Create a mock API response in the new `limits`-array format.

    Args:
        session_percent: 5-hour session utilization (None omits the session entry).
        weekly_percent: 7-day weekly-all utilization (None omits the weekly_all entry).
        models: {display_name: (percent, resets_at)} weekly-scoped per-model limits.
        session_reset / weekly_reset: reset timestamps for the session/weekly entries.
    """
    limits: list[dict] = []
    if session_percent is not None:
        limits.append(_limit("session", "session", session_percent, session_reset))
    if weekly_percent is not None:
        limits.append(_limit("weekly_all", "weekly", weekly_percent, weekly_reset))
    for name, (percent, reset) in (models or {}).items():
        limits.append(_limit("weekly_scoped", "weekly", percent, reset, model=name))
    return {"limits": limits}


def make_legacy_api_response(
    five_hour_util: float | None = 45.0,
    seven_day_util: float | None = 32.0,
    sonnet_util: float | None = 15.0,
    five_hour_reset: str | None = "2026-01-27T18:00:00+00:00",
    seven_day_reset: str | None = "2026-01-30T17:00:00+00:00",
    sonnet_reset: str | None = None,
) -> dict:
    """Create a mock API response in the legacy top-level format (no `limits` array).

    Includes junk codename keys that must be ignored by the parser.
    """
    response: dict = {
        "five_hour": {"utilization": five_hour_util, "resets_at": five_hour_reset},
        "seven_day": {"utilization": seven_day_util, "resets_at": seven_day_reset},
        # Junk codenames the parser must ignore:
        "seven_day_cowork": None,
        "seven_day_omelette": None,
        "tangelo": None,
    }
    if sonnet_util is not None:
        response["seven_day_sonnet"] = {
            "utilization": sonnet_util,
            "resets_at": sonnet_reset if sonnet_reset is not None else seven_day_reset,
        }
    return response
