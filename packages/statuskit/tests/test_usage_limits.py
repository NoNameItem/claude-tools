"""Tests for usage_limits module."""

from datetime import UTC, datetime

from statuskit.modules.usage_limits import (
    UsageData,
    UsageLimit,
    calculate_color,
    parse_api_response,
)

from tests.factories.usage_limits import make_api_response


class TestUsageLimit:
    """Tests for UsageLimit dataclass."""

    def test_create_usage_limit(self):
        """UsageLimit stores utilization and reset time."""
        reset_time = datetime(2026, 1, 27, 18, 0, 0, tzinfo=UTC)
        limit = UsageLimit(utilization=45.0, resets_at=reset_time)

        assert limit.utilization == 45.0
        assert limit.resets_at == reset_time


class TestUsageData:
    """Tests for UsageData dataclass."""

    def test_create_usage_data_full(self):
        """UsageData stores all three limit types."""
        now = datetime.now(UTC)
        session = UsageLimit(utilization=45.0, resets_at=now)
        weekly = UsageLimit(utilization=32.0, resets_at=now)
        sonnet = UsageLimit(utilization=15.0, resets_at=now)

        data = UsageData(
            session=session,
            weekly=weekly,
            sonnet=sonnet,
            fetched_at=now,
        )

        assert data.session == session
        assert data.weekly == weekly
        assert data.sonnet == sonnet
        assert data.fetched_at == now

    def test_create_usage_data_partial(self):
        """UsageData allows None for optional limits."""
        now = datetime.now(UTC)
        session = UsageLimit(utilization=45.0, resets_at=now)

        data = UsageData(
            session=session,
            weekly=None,
            sonnet=None,
            fetched_at=now,
        )

        assert data.session == session
        assert data.weekly is None
        assert data.sonnet is None


class TestParseApiResponse:
    """Tests for API response parsing."""

    def test_parse_full_response(self):
        """Parse response with all three limits."""
        response = make_api_response()
        data = parse_api_response(response)

        assert data.session is not None
        assert data.session.utilization == 45.0
        assert data.session.resets_at == datetime(2026, 1, 27, 18, 0, 0, tzinfo=UTC)

        assert data.weekly is not None
        assert data.weekly.utilization == 32.0

        assert data.sonnet is not None
        assert data.sonnet.utilization == 15.0

    def test_parse_response_without_sonnet(self):
        """Parse response without seven_day_sonnet."""
        response = make_api_response(sonnet_util=None)
        data = parse_api_response(response)

        assert data.session is not None
        assert data.weekly is not None
        assert data.sonnet is None

    def test_parse_response_records_fetch_time(self):
        """Parsed data includes fetch timestamp."""
        response = make_api_response()
        before = datetime.now(UTC)
        data = parse_api_response(response)
        after = datetime.now(UTC)

        assert before <= data.fetched_at <= after


class TestCalculateColor:
    """Tests for color calculation based on utilization vs time."""

    def test_red_when_over_time_percent(self):
        """Red when utilization exceeds time percent."""
        # 2.5h passed of 5h window = 50% time, 60% usage = over
        color = calculate_color(
            utilization=60.0,
            remaining_hours=2.5,
            window_hours=5.0,
        )
        assert color == "red"

    def test_yellow_when_within_margin(self):
        """Yellow when utilization is within 10% margin of time percent."""
        # 2.5h passed of 5h window = 50% time, 45% usage = within margin
        color = calculate_color(
            utilization=45.0,
            remaining_hours=2.5,
            window_hours=5.0,
        )
        assert color == "yellow"

    def test_green_when_well_under(self):
        """Green when utilization is well under time percent."""
        # 2.5h passed of 5h window = 50% time, 35% usage = under
        color = calculate_color(
            utilization=35.0,
            remaining_hours=2.5,
            window_hours=5.0,
        )
        assert color == "green"

    def test_yellow_at_80_percent_time_75_usage(self):
        """Yellow at 80% time with 75% usage."""
        # 1h remaining of 5h = 80% time, 75% usage
        color = calculate_color(
            utilization=75.0,
            remaining_hours=1.0,
            window_hours=5.0,
        )
        assert color == "yellow"

    def test_green_at_80_percent_time_65_usage(self):
        """Green at 80% time with 65% usage."""
        # 1h remaining of 5h = 80% time, 65% usage
        color = calculate_color(
            utilization=65.0,
            remaining_hours=1.0,
            window_hours=5.0,
        )
        assert color == "green"

    def test_weekly_window(self):
        """Works correctly for 7-day window."""
        # 3.5 days remaining of 7 days = 50% time, 60% usage = red
        color = calculate_color(
            utilization=60.0,
            remaining_hours=3.5 * 24,
            window_hours=7 * 24,
        )
        assert color == "red"
