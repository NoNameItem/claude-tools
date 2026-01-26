"""Tests for usage_limits module."""

from datetime import UTC, datetime

from statuskit.modules.usage_limits import UsageData, UsageLimit, parse_api_response

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
