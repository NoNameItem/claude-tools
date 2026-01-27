"""Tests for usage_limits module."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from statuskit.modules.usage_limits import (
    UsageCache,
    UsageData,
    UsageLimit,
    UsageLimitsModule,
    calculate_color,
    fetch_usage_api,
    format_progress_bar,
    format_remaining_time,
    format_reset_at,
    get_token,
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


class TestFormatRemainingTime:
    """Tests for remaining time formatting."""

    def test_under_one_hour(self):
        """Format as minutes when under 1 hour."""
        assert format_remaining_time(0.75) == "45m"
        assert format_remaining_time(0.5) == "30m"

    def test_one_to_24_hours(self):
        """Format as hours and minutes when 1-24 hours."""
        assert format_remaining_time(2.5) == "2h 30m"
        assert format_remaining_time(1.0) == "1h 0m"
        assert format_remaining_time(23.5) == "23h 30m"

    def test_over_24_hours(self):
        """Format as days and hours when over 24 hours."""
        assert format_remaining_time(27.0) == "1d 3h"
        assert format_remaining_time(72.0) == "3d 0h"
        assert format_remaining_time(123.5) == "5d 3h"


class TestFormatResetAt:
    """Tests for reset_at time formatting."""

    def test_format_weekday_time(self):
        """Format as weekday and time in local timezone."""
        # Thursday 17:00 UTC
        reset_time = datetime(2026, 1, 29, 17, 0, 0, tzinfo=UTC)
        result = format_reset_at(reset_time)
        # Result depends on local timezone, just check format
        assert len(result.split()) == 2  # "Thu 17:00" or similar
        assert ":" in result  # Contains time


class TestFormatProgressBar:
    """Tests for progress bar formatting."""

    def test_empty_bar(self):
        """0% utilization shows empty bar."""
        result = format_progress_bar(0.0, width=10)
        assert result == "[░░░░░░░░░░]"

    def test_full_bar(self):
        """100% utilization shows full bar."""
        result = format_progress_bar(100.0, width=10)
        assert result == "[██████████]"

    def test_half_bar(self):
        """50% utilization shows half-filled bar."""
        result = format_progress_bar(50.0, width=10)
        assert result == "[█████░░░░░]"

    def test_partial_bar(self):
        """45% utilization rounds to 4 filled chars."""
        result = format_progress_bar(45.0, width=10)
        assert result == "[████░░░░░░]"

    def test_custom_width(self):
        """Respects custom width."""
        result = format_progress_bar(50.0, width=6)
        assert result == "[███░░░]"


class TestGetToken:
    """Tests for OAuth token retrieval."""

    def test_get_token_from_keychain(self):
        """Gets token from macOS Keychain first."""
        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = "keychain-token"
            token = get_token()
            assert token == "keychain-token"  # noqa: S105

    def test_fallback_to_credentials_file(self, tmp_path):
        """Falls back to credentials file if Keychain fails."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "file-token"}}))

        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = None
            with patch("statuskit.modules.usage_limits.CREDENTIALS_PATH", creds_file):
                token = get_token()
                assert token == "file-token"  # noqa: S105

    def test_returns_none_when_no_token(self, tmp_path):
        """Returns None when token not found anywhere."""
        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = None
            with patch("statuskit.modules.usage_limits.CREDENTIALS_PATH", tmp_path / "nonexistent"):
                token = get_token()
                assert token is None


class TestFetchUsageApi:
    """Tests for API fetching."""

    def test_fetch_success(self):
        """Successful API call returns parsed data."""
        response_data = json.dumps(make_api_response()).encode()

        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = response_data
            mock_response.status = 200

            data = fetch_usage_api("test-token")

            assert data is not None
            assert data.session is not None
            assert data.session.utilization == 45.0

    def test_fetch_timeout(self):
        """Returns None on timeout."""
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timeout")
            data = fetch_usage_api("test-token")
            assert data is None

    def test_fetch_error(self):
        """Returns None on URL error."""
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("connection failed")
            data = fetch_usage_api("test-token")
            assert data is None


class TestUsageCache:
    """Tests for usage data caching."""

    def test_save_and_load(self, tmp_path):
        """Cache saves and loads data."""
        cache = UsageCache(cache_dir=tmp_path, ttl=60)
        data = UsageData(
            session=UsageLimit(45.0, datetime.now(UTC)),
            weekly=None,
            sonnet=None,
            fetched_at=datetime.now(UTC),
        )

        cache.save(data)
        loaded = cache.load()

        assert loaded is not None
        assert loaded.session is not None
        assert loaded.session.utilization == 45.0

    def test_load_returns_none_when_expired(self, tmp_path):
        """Cache returns None when TTL expired."""
        cache = UsageCache(cache_dir=tmp_path, ttl=0)  # 0 TTL = always expired
        data = UsageData(
            session=UsageLimit(45.0, datetime.now(UTC)),
            weekly=None,
            sonnet=None,
            fetched_at=datetime.now(UTC),
        )

        cache.save(data)
        loaded = cache.load()

        assert loaded is None

    def test_load_returns_none_when_no_cache(self, tmp_path):
        """Cache returns None when file doesn't exist."""
        cache = UsageCache(cache_dir=tmp_path, ttl=60)
        loaded = cache.load()
        assert loaded is None

    def test_can_fetch_respects_rate_limit(self, tmp_path):
        """Rate limit prevents fetching too frequently."""
        cache = UsageCache(cache_dir=tmp_path, ttl=60, rate_limit=30)

        # First fetch allowed
        assert cache.can_fetch() is True
        cache.mark_fetched()

        # Second fetch blocked
        assert cache.can_fetch() is False

    def test_load_stale_returns_expired_data(self, tmp_path):
        """load_stale returns data even when TTL expired."""
        cache = UsageCache(cache_dir=tmp_path, ttl=0)  # 0 TTL = always expired
        data = UsageData(
            session=UsageLimit(45.0, datetime.now(UTC)),
            weekly=None,
            sonnet=None,
            fetched_at=datetime.now(UTC),
        )

        cache.save(data)

        # Regular load returns None (TTL expired)
        assert cache.load() is None

        # load_stale returns data anyway
        loaded = cache.load_stale()
        assert loaded is not None
        assert loaded.session.utilization == 45.0

    def test_save_is_atomic(self, tmp_path):
        """Save uses atomic write (temp file + rename)."""
        cache = UsageCache(cache_dir=tmp_path, ttl=60)
        data = UsageData(
            session=UsageLimit(45.0, datetime.now(UTC)),
            weekly=None,
            sonnet=None,
            fetched_at=datetime.now(UTC),
        )

        with patch.object(tempfile, "NamedTemporaryFile") as mock_tmp:
            # Setup mock temp file
            mock_file = mock_tmp.return_value.__enter__.return_value
            mock_file.name = str(tmp_path / "temp_file.tmp")

            with patch.object(Path, "replace") as mock_replace:
                cache.save(data)

                # Verify temp file was used
                mock_tmp.assert_called_once()
                call_kwargs = mock_tmp.call_args[1]
                assert call_kwargs["dir"] == tmp_path
                assert call_kwargs["delete"] is False

                # Verify atomic rename was called
                mock_replace.assert_called_once()


class TestUsageLimitsModule:
    """Tests for UsageLimitsModule rendering."""

    def test_render_multiline_default(self, make_render_context, minimal_input_data, tmp_path):
        """Renders multiline format by default."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {}

        # Mock data retrieval
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                session=UsageLimit(45.0, datetime.now(UTC) + timedelta(hours=2.5)),
                weekly=UsageLimit(32.0, datetime.now(UTC) + timedelta(days=3)),
                sonnet=None,
                fetched_at=datetime.now(UTC),
            )

            module = UsageLimitsModule(ctx, config)
            output = module.render()

            assert output is not None
            assert "Usage:" in output
            assert "Session:" in output
            assert "45%" in output
            assert "Weekly:" in output
            assert "32%" in output

    def test_render_returns_none_when_no_data(self, make_render_context, minimal_input_data, tmp_path):
        """Returns None when no usage data available."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {}

        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = None

            module = UsageLimitsModule(ctx, config)
            output = module.render()

            assert output is None

    def test_render_single_line(self, make_render_context, minimal_input_data, tmp_path):
        """Renders single-line when multiline=false."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {"multiline": False}

        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                session=UsageLimit(45.0, datetime.now(UTC) + timedelta(hours=2.5)),
                weekly=UsageLimit(32.0, datetime.now(UTC) + timedelta(days=3)),
                sonnet=None,
                fetched_at=datetime.now(UTC),
            )

            module = UsageLimitsModule(ctx, config)
            output = module.render()

            assert output is not None
            assert output.count("\n") == 0  # Single line
            assert "5h" in output
            assert "7d" in output

    def test_render_with_progress_bar(self, make_render_context, minimal_input_data, tmp_path):
        """Renders with progress bar when enabled."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {"show_progress_bar": True}

        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                session=UsageLimit(45.0, datetime.now(UTC) + timedelta(hours=2.5)),
                weekly=None,
                sonnet=None,
                fetched_at=datetime.now(UTC),
            )

            module = UsageLimitsModule(ctx, config)
            output = module.render()

            assert output is not None
            assert "[" in output  # Progress bar brackets
            assert "]" in output


class TestUsageLimitsIntegration:
    """Integration tests for usage_limits module."""

    def test_full_flow_with_mock_api(self, make_render_context, minimal_input_data, tmp_path):
        """Full flow: API fetch -> cache -> render."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {"cache_ttl": 60}

        # Mock token and API
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"

            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = UsageData(
                    session=UsageLimit(45.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    weekly=UsageLimit(32.0, datetime.now(UTC) + timedelta(days=3)),
                    sonnet=None,
                    fetched_at=datetime.now(UTC),
                )

                module = UsageLimitsModule(ctx, config)
                output = module.render()

                assert output is not None
                assert "Session:" in output
                assert "Weekly:" in output

                # Verify cache was saved
                cache_file = tmp_path / "usage_limits.json"
                assert cache_file.exists()

                # Second render uses cache
                mock_fetch.reset_mock()
                output2 = module.render()
                mock_fetch.assert_not_called()  # Used cache
                assert output2 is not None


class TestGetUsageDataRateLimited:
    """Tests for _get_usage_data when rate limited."""

    def test_returns_stale_data_when_rate_limited(self, make_render_context, minimal_input_data, tmp_path):
        """Returns stale cache when rate limited and TTL expired."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        config = {"cache_ttl": 0}  # TTL=0 means cache always "expired"

        module = UsageLimitsModule(ctx, config)

        # Prepare stale cache with rate limit active
        stale_data = UsageData(
            session=UsageLimit(45.0, datetime.now(UTC) + timedelta(hours=2.5)),
            weekly=None,
            sonnet=None,
            fetched_at=datetime.now(UTC),
        )
        module.cache.save(stale_data)
        module.cache.mark_fetched()  # Activate rate limit

        # Verify setup: TTL expired, rate limit active
        assert module.cache.load() is None  # TTL expired
        assert module.cache.can_fetch() is False  # Rate limited

        # _get_usage_data should return stale data, not None
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            result = module._get_usage_data()

        assert result is not None
        assert result.session.utilization == 45.0
