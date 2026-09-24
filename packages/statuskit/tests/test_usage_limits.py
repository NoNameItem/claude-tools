"""Tests for usage_limits module."""

import json
import re
import tempfile
import time
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
from statuskit.core.models import RateLimits, RateLimitWindow
from statuskit.modules.usage_limits import (
    API_URL,
    RETRY_AFTER_FALLBACK,
    RETRY_AFTER_MAX,
    FetchOutcome,
    UsageCache,
    UsageData,
    UsageGroup,
    UsageLimit,
    UsageLimitsModule,
    _parse_retry_after,
    calculate_color,
    fetch_usage_api,
    format_progress_bar,
    format_remaining_time,
    format_reset_at,
    get_token,
    parse_api_response,
)

from tests.factories import make_input_data, make_model_data
from tests.factories.usage_limits import make_api_response, make_legacy_api_response

SESSION_WINDOW = 5.0
WEEKLY_WINDOW = 168.0


def _group(data: UsageData, key: str) -> UsageGroup | None:
    return next((g for g in data.groups if g.key == key), None)


class TestDataModel:
    """UsageLimit / UsageGroup / UsageData dataclasses."""

    def test_usage_limit_fields(self):
        reset = datetime(2026, 1, 27, 18, 0, 0, tzinfo=UTC)
        limit = UsageLimit(label="Session", utilization=45.0, resets_at=reset)
        assert limit.label == "Session"
        assert limit.utilization == 45.0
        assert limit.resets_at == reset

    def test_usage_group_defaults(self):
        group = UsageGroup(key="weekly", window_hours=WEEKLY_WINDOW)
        assert group.overall is None
        assert group.models == []

    def test_usage_data_leaves_last_attempt_at_none_when_omitted(self):
        """No default from `fetched_at`: omitting it must mean "no attempt", not "just now".

        Only `UsageCache.claim_attempt` / `_apply_outcome` are allowed to set it — a `UsageData`
        fabricated for another reason (e.g. `_persist_payload`'s cold-cache stand-in) must not
        look like a completed attempt and wrongly throttle the next real fetch.
        """
        data = UsageData(groups=[], fetched_at=datetime.now(UTC))
        assert data.last_attempt_at is None


class TestParseLimitsArray:
    """Parsing the new `limits` array."""

    def test_parses_session_and_weekly_overall(self):
        data = parse_api_response(make_api_response())
        session = _group(data, "session")
        weekly = _group(data, "weekly")
        assert session is not None
        assert session.overall is not None
        assert session.overall.label == "Session"
        assert session.overall.utilization == 11.0
        assert session.window_hours == SESSION_WINDOW
        assert weekly is not None
        assert weekly.overall is not None
        assert weekly.overall.label == "Weekly"
        assert weekly.window_hours == WEEKLY_WINDOW

    def test_group_order_is_session_then_weekly(self):
        data = parse_api_response(make_api_response())
        assert [g.key for g in data.groups] == ["session", "weekly"]

    def test_parses_scoped_models_under_weekly(self):
        data = parse_api_response(
            make_api_response(models={"Fable": (34.0, "2026-01-30T03:59:00+00:00"), "Opus": (88.0, None)})
        )
        weekly = _group(data, "weekly")
        assert weekly is not None
        labels = [m.label for m in weekly.models]
        assert labels == ["Fable", "Opus"]
        fable = weekly.models[0]
        assert fable.utilization == 34.0
        assert fable.resets_at == datetime(2026, 1, 30, 3, 59, 0, tzinfo=UTC)
        assert weekly.models[1].resets_at is None

    def test_skips_scoped_without_display_name(self):
        response = make_api_response()
        response["limits"].append(
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": 5.0,
                "resets_at": None,
                "scope": {"model": {"id": None, "display_name": None}},
                "is_active": False,
            }
        )
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.models == []

    def test_scoped_non_model_limit_does_not_overwrite_overall(self):
        # A surface-scoped limit is its own row, keyed by (model=None, surface="code") and
        # labeled with the raw surface. It must never become the group's scope-less overall.
        response = {
            "limits": [
                {"kind": "weekly_all", "group": "weekly", "percent": 42.0, "resets_at": None, "scope": None},
                {
                    "kind": "weekly_surface",
                    "group": "weekly",
                    "percent": 99.0,
                    "resets_at": None,
                    "scope": {"model": None, "surface": "code"},
                },
            ]
        }
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.overall is not None
        assert weekly.overall.utilization == 42.0
        assert [(m.label, m.model, m.surface) for m in weekly.models] == [("code", None, "code")]

    def test_model_and_surface_are_distinct_rows(self):
        # The whole point of keying by the pair: a narrower model+surface quota must not be
        # mistaken for — or collapsed into — the model-wide one.
        response = {
            "limits": [
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 10.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": "Fable"}, "surface": None},
                },
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 70.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": "Fable"}, "surface": "cli"},
                },
            ]
        }
        weekly = _group(parse_api_response(response), "weekly")
        assert weekly is not None
        assert [(m.label, m.model, m.surface, m.utilization) for m in weekly.models] == [
            ("Fable", "Fable", None, 10.0),
            ("Fable·cli", "Fable", "cli", 70.0),
        ]

    def test_duplicate_scope_keeps_first_row(self):
        # Two rows for the same (model, surface) pair are an API anomaly — never double-count.
        response = {
            "limits": [
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 10.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": "Fable"}, "surface": None},
                },
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 99.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": "Fable"}, "surface": None},
                },
            ]
        }
        weekly = _group(parse_api_response(response), "weekly")
        assert weekly is not None
        assert [(m.label, m.utilization) for m in weekly.models] == [("Fable", 10.0)]

    def test_boolean_percent_is_rejected(self):
        # float(True) is 1.0 — a malformed boolean would otherwise render as a bogus 1% quota.
        response = {
            "limits": [
                {"kind": "weekly_all", "group": "weekly", "percent": True, "resets_at": None, "scope": None},
                {"kind": "session", "group": "session", "percent": False, "resets_at": None, "scope": None},
            ]
        }
        assert parse_api_response(response).groups == []

    def test_string_percent_is_rejected(self):
        # Same gate on both parsers: the cache path already rejected non-numerics, the API path
        # silently coerced them. A numeric-looking string is still a shape change.
        response = {
            "limits": [{"kind": "weekly_all", "group": "weekly", "percent": "42", "resets_at": None, "scope": None}]
        }
        assert parse_api_response(response).groups == []

    def test_scoped_with_non_dict_model_is_skipped(self):
        # `model` as a bare id string (an API shape change) must not raise AttributeError out of
        # the parser — one malformed entry would otherwise suppress the whole usage module.
        response = {
            "limits": [
                {"kind": "weekly_all", "group": "weekly", "percent": 42.0, "resets_at": None, "scope": None},
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 7.0,
                    "resets_at": None,
                    "scope": {"model": "claude-fable-5"},
                },
            ]
        }
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.overall is not None
        assert weekly.overall.utilization == 42.0
        assert weekly.models == []

    def test_scoped_with_non_string_display_name_is_skipped(self):
        # A truthy non-str label would reach _visible_groups' .casefold() and crash the render.
        response = {
            "limits": [
                {"kind": "weekly_all", "group": "weekly", "percent": 42.0, "resets_at": None, "scope": None},
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 7.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": 12345}},
                },
                {
                    "kind": "weekly_scoped",
                    "group": "weekly",
                    "percent": 8.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": {"nested": "object"}}},
                },
            ]
        }
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.models == []
        assert weekly.overall is not None
        assert weekly.overall.utilization == 42.0

    def test_non_finite_utilization_is_skipped(self):
        # json.loads() accepts the bare NaN / Infinity tokens, and a non-finite value survives
        # float() only to crash the renderer: int(nan / 100 * width) raises ValueError.
        response = json.loads(
            '{"limits": ['
            '{"kind":"weekly_all","group":"weekly","percent":NaN,"resets_at":null,"scope":null},'
            '{"kind":"session","group":"session","percent":Infinity,"resets_at":null,"scope":null}'
            "]}"
        )
        assert parse_api_response(response).groups == []

    def test_oversized_integer_utilization_is_skipped(self):
        # json.loads() turns a long integer literal into an int too large for a float, and
        # math.isfinite() raises OverflowError on it instead of returning False.
        huge = "1" + "0" * 400
        response = json.loads(
            '{"limits": [{"kind":"session","group":"session","percent":' + huge + ',"resets_at":null,"scope":null}]}'
        )
        assert parse_api_response(response).groups == []

    def test_non_dict_response_yields_no_groups(self):
        # json.loads() can hand back a list or a string; the parser must degrade, not raise.
        assert parse_api_response(["not", "a", "dict"]).groups == []

    def test_legacy_keys_with_non_dict_values_are_skipped(self):
        # `x or {}` lets a truthy non-dict through; the following .get() would raise.
        response = {"five_hour": "unavailable", "seven_day": 0, "seven_day_sonnet": ["nope"]}
        assert parse_api_response(response).groups == []

    def test_scoped_non_model_limit_alone_is_a_row_not_the_overall(self):
        # A lone surface-scoped item forms the group (as a scoped row) but leaves `overall` unset,
        # so the renderer never presents it as the group-wide Weekly percentage.
        response = {
            "limits": [
                {
                    "kind": "weekly_surface",
                    "group": "weekly",
                    "percent": 99.0,
                    "resets_at": None,
                    "scope": {"surface": "code"},
                },
            ]
        }
        weekly = _group(parse_api_response(response), "weekly")
        assert weekly is not None
        assert weekly.overall is None
        assert [(m.label, m.model, m.surface) for m in weekly.models] == [("code", None, "code")]

    def test_scope_object_without_usable_model_or_surface_is_skipped(self):
        # An empty/unusable scope object keys nothing — it is neither overall nor a scoped row.
        response = {
            "limits": [
                {"kind": "x", "group": "weekly", "percent": 5.0, "resets_at": None, "scope": {}},
                {
                    "kind": "y",
                    "group": "weekly",
                    "percent": 6.0,
                    "resets_at": None,
                    "scope": {"model": {"display_name": ""}, "surface": ""},
                },
            ]
        }
        assert parse_api_response(response).groups == []

    def test_skips_null_percent_overall(self):
        response = {
            "limits": [
                {"kind": "session", "group": "session", "percent": None, "resets_at": None, "scope": None},
                {"kind": "weekly_all", "group": "weekly", "percent": 2.0, "resets_at": None, "scope": None},
            ]
        }
        data = parse_api_response(response)
        session = _group(data, "session")
        # Session group has no valid overall and no models -> not emitted.
        assert session is None

    def test_ignores_unknown_group(self):
        response = {
            "limits": [
                {"kind": "monthly", "group": "monthly", "percent": 50.0, "resets_at": None, "scope": None},
                {"kind": "session", "group": "session", "percent": 11.0, "resets_at": None, "scope": None},
            ]
        }
        data = parse_api_response(response)
        assert [g.key for g in data.groups] == ["session"]

    def test_records_fetch_time(self):
        before = datetime.now(UTC)
        data = parse_api_response(make_api_response())
        after = datetime.now(UTC)
        assert before <= data.fetched_at <= after

    def test_non_numeric_percent_skipped(self):
        response = make_api_response()
        response["limits"].append(
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": "n/a",
                "resets_at": None,
                "scope": {"model": {"id": None, "display_name": "Fable"}},
                "is_active": False,
            }
        )
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert "Fable" not in [m.label for m in weekly.models]


class TestParseLegacyFallback:
    """Parsing legacy top-level keys when `limits` is absent."""

    def test_falls_back_to_top_level_keys(self):
        data = parse_api_response(make_legacy_api_response())
        session = _group(data, "session")
        weekly = _group(data, "weekly")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 45.0
        assert weekly is not None
        assert weekly.overall is not None
        assert weekly.overall.utilization == 32.0
        assert [m.label for m in weekly.models] == ["Sonnet"]
        assert weekly.models[0].utilization == 15.0

    def test_junk_codenames_are_ignored(self):
        data = parse_api_response(make_legacy_api_response())
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert [m.label for m in weekly.models] == ["Sonnet"]

    def test_legacy_without_sonnet(self):
        data = parse_api_response(make_legacy_api_response(sonnet_util=None))
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.models == []

    def test_legacy_sonnet_null_utilization_skipped(self):
        response = make_legacy_api_response()
        response["seven_day_sonnet"] = {"utilization": None, "resets_at": None}
        data = parse_api_response(response)
        weekly = _group(data, "weekly")
        assert weekly is not None
        assert weekly.models == []

    def test_empty_limits_array_uses_legacy(self):
        response = make_legacy_api_response()
        response["limits"] = []
        data = parse_api_response(response)
        session = _group(data, "session")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 45.0


class TestCalculateColor:
    """Color calculation based on utilization vs time (unchanged behavior)."""

    def test_red_when_over_time_percent(self):
        assert calculate_color(utilization=60.0, remaining_hours=2.5, window_hours=5.0) == "red"

    def test_yellow_when_within_margin(self):
        assert calculate_color(utilization=45.0, remaining_hours=2.5, window_hours=5.0) == "yellow"

    def test_green_when_well_under(self):
        assert calculate_color(utilization=35.0, remaining_hours=2.5, window_hours=5.0) == "green"

    def test_weekly_window(self):
        assert calculate_color(utilization=60.0, remaining_hours=3.5 * 24, window_hours=7 * 24) == "red"


class TestFormatRemainingTime:
    def test_under_one_hour(self):
        assert format_remaining_time(0.75) == "45m"

    def test_one_to_24_hours(self):
        assert format_remaining_time(2.5) == "2h 30m"

    def test_over_24_hours(self):
        assert format_remaining_time(27.0) == "1d 3h"


class TestFormatResetAt:
    @pytest.fixture
    def east_of_utc(self, monkeypatch):
        """Local timezone UTC+3, so astimezone() moves a UTC time forward."""
        monkeypatch.setenv("TZ", "Etc/GMT-3")  # the POSIX sign is inverted: this is UTC+3
        time.tzset()
        yield
        monkeypatch.undo()
        time.tzset()

    def test_format_weekday_time(self):
        result = format_reset_at(datetime(2026, 1, 29, 17, 0, 0, tzinfo=UTC))
        assert len(result.split()) == 2
        assert ":" in result

    @pytest.mark.usefixtures("east_of_utc")
    def test_reset_near_datetime_max_falls_back_to_utc(self):
        # East of UTC, astimezone() pushes the last representable UTC minute past datetime.max.
        assert format_reset_at(datetime.max.replace(tzinfo=UTC)) == "Fri 23:59"


class TestFormatProgressBar:
    def test_empty_bar(self):
        assert format_progress_bar(0.0, width=10) == "[░░░░░░░░░░]"

    def test_full_bar(self):
        assert format_progress_bar(100.0, width=10) == "[██████████]"

    def test_half_bar(self):
        assert format_progress_bar(50.0, width=10) == "[█████░░░░░]"

    def test_out_of_range_utilization_is_clamped(self):
        # An untrusted percent may be any finite float: 1e20 overflowed the repeat count, and
        # 1e9..1e19 would have built a multi-GB bar.
        assert format_progress_bar(1e20, width=10) == "[██████████]"
        assert format_progress_bar(150.0, width=10) == "[██████████]"
        assert format_progress_bar(-1e20, width=10) == "[░░░░░░░░░░]"


class TestGetToken:
    def test_get_token_from_keychain(self):
        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = "keychain-token"
            assert get_token() == "keychain-token"

    def test_fallback_to_credentials_file(self, tmp_path):
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "file-token"}}))
        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = None
            with patch("statuskit.modules.usage_limits.CREDENTIALS_PATH", creds_file):
                assert get_token() == "file-token"

    def test_returns_none_when_no_token(self, tmp_path):
        with patch("statuskit.modules.usage_limits._get_keychain_token") as mock_keychain:
            mock_keychain.return_value = None
            with patch("statuskit.modules.usage_limits.CREDENTIALS_PATH", tmp_path / "nonexistent"):
                assert get_token() is None


class TestFetchUsageApi:
    """The usage-API call and how each outcome is reported."""

    def test_successful_fetch_returns_data(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = json.dumps(make_api_response()).encode()
            outcome = fetch_usage_api("test-token")
        assert outcome.data is not None
        assert outcome.data.groups
        assert outcome.retry_after is None
        assert outcome.status is None

    def test_timeout_reports_the_error_class(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timeout")
            outcome = fetch_usage_api("test-token")
        assert outcome.data is None
        assert outcome.error == "timeout"

    def test_network_error_reports_the_error_class(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("connection failed")
            outcome = fetch_usage_api("test-token")
        assert outcome.data is None
        assert outcome.error == "network error"

    def test_bad_json_reports_the_error_class(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{not json"
            outcome = fetch_usage_api("test-token")
        assert outcome.data is None
        assert outcome.error == "bad JSON"

    def test_429_carries_retry_after_seconds(self):
        headers = Message()
        headers["Retry-After"] = "1198"
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(url=API_URL, code=429, msg="Too Many Requests", hdrs=headers, fp=None)
            outcome = fetch_usage_api("test-token")
        assert outcome.data is None
        assert outcome.status == 429
        assert outcome.retry_after == 1198.0

    def test_429_without_a_usable_header_falls_back(self):
        for value in (None, "", "soon", "-5"):
            headers = Message()
            if value is not None:
                headers["Retry-After"] = value
            with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = HTTPError(url=API_URL, code=429, msg="rate", hdrs=headers, fp=None)
                outcome = fetch_usage_api("test-token")
            assert outcome.retry_after == RETRY_AFTER_FALLBACK

    def test_other_http_error_reports_the_status(self):
        headers = Message()
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(url=API_URL, code=401, msg="Unauthorized", hdrs=headers, fp=None)
            outcome = fetch_usage_api("test-token")
        assert outcome.data is None
        assert outcome.status == 401
        assert outcome.retry_after is None

    def test_parse_retry_after_accepts_plain_seconds(self):
        assert _parse_retry_after("92") == 92.0
        assert _parse_retry_after(" 92 ") == 92.0
        assert _parse_retry_after("0") == 0.0

    def test_parse_retry_after_caps_the_delay(self):
        assert _parse_retry_after("3599") == 3599.0
        assert _parse_retry_after("3601") == RETRY_AFTER_MAX
        assert _parse_retry_after("1000000000000") == RETRY_AFTER_MAX


def _session_group(util: float, resets_at: datetime | None) -> UsageGroup:
    return UsageGroup("session", SESSION_WINDOW, overall=UsageLimit("Session", util, resets_at))


def _weekly_group(util: float | None, resets_at: datetime | None, models: list[UsageLimit] | None = None) -> UsageGroup:
    overall = UsageLimit("Weekly", util, resets_at) if util is not None else None
    return UsageGroup("weekly", WEEKLY_WINDOW, overall=overall, models=models or [])


def _payload_ctx(make_render_context, tmp_path, *, five_hour=(46.0, None), seven_day=(15.0, None), debug=False):
    """Render context whose statusline payload carries `rate_limits`.

    Reset times are given as offsets in hours from now, or None for "no reset time".
    """

    def epoch(offset_hours):
        if offset_hours is None:
            return None
        return int((datetime.now(UTC) + timedelta(hours=offset_hours)).timestamp())

    block = {}
    if five_hour is not None:
        block["five_hour"] = {"used_percentage": five_hour[0], "resets_at": epoch(five_hour[1])}
    if seven_day is not None:
        block["seven_day"] = {"used_percentage": seven_day[0], "resets_at": epoch(seven_day[1])}
    return make_render_context(
        make_input_data(model=make_model_data(), rate_limits=block), debug=debug, cache_dir=tmp_path
    )


class TestUsageCache:
    """Cache save/load for the grouped format."""

    def test_save_and_load_roundtrip(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path)
        now = datetime.now(UTC)
        data = UsageData(
            groups=[
                _session_group(11.0, now),
                _weekly_group(2.0, now, models=[UsageLimit("Fable", 34.0, now), UsageLimit("Opus", 0.0, None)]),
            ],
            fetched_at=now,
        )
        cache.save(data)
        loaded = cache.load()
        assert loaded is not None
        session = _group(loaded, "session")
        weekly = _group(loaded, "weekly")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 11.0
        assert session.window_hours == SESSION_WINDOW
        assert weekly is not None
        assert [m.label for m in weekly.models] == ["Fable", "Opus"]
        assert weekly.models[0].utilization == 34.0
        assert weekly.models[1].resets_at is None

    def test_load_returns_none_when_no_cache(self, tmp_path):
        assert UsageCache(cache_dir=tmp_path).load() is None

    def test_save_is_atomic(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path)
        data = UsageData(groups=[_session_group(45.0, datetime.now(UTC))], fetched_at=datetime.now(UTC))
        with patch.object(tempfile, "NamedTemporaryFile") as mock_tmp:
            mock_file = mock_tmp.return_value.__enter__.return_value
            mock_file.name = str(tmp_path / "temp_file.tmp")
            with patch.object(Path, "replace") as mock_replace:
                cache.save(data)
                mock_tmp.assert_called_once()
                assert mock_tmp.call_args[1]["dir"] == tmp_path
                assert mock_tmp.call_args[1]["delete"] is False
                mock_replace.assert_called_once()

    def test_save_reports_success_and_failure_via_last_save_ok(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path)
        data = UsageData(groups=[_session_group(45.0, datetime.now(UTC))], fetched_at=datetime.now(UTC))

        cache.save(data)
        assert cache.last_save_ok is True

        with patch.object(Path, "replace", side_effect=OSError("disk full")):
            cache.save(data)
        assert cache.last_save_ok is False

        # A later successful save clears the flag rather than latching the earlier failure.
        cache.save(data)
        assert cache.last_save_ok is True

    def test_old_format_cache_keeps_timestamps_without_limits(self, tmp_path):
        """Legacy cache (session/weekly/sonnet dict): limits are a miss, timestamps survive.

        The timestamps are the only thing throttling the API — dropping them (returning None)
        would make a failing API get re-hit on every render.
        """
        cache = UsageCache(cache_dir=tmp_path)
        (tmp_path / "usage_limits.json").write_text(
            json.dumps(
                {
                    "data": {
                        "session": {"utilization": 45.0, "resets_at": "2026-01-27T18:00:00+00:00"},
                        "weekly": {"utilization": 32.0, "resets_at": "2026-01-30T17:00:00+00:00"},
                        "sonnet": {"utilization": 0.0, "resets_at": None},
                    },
                    "fetched_at": "2026-01-27T12:00:00+00:00",
                    "last_attempt_at": "2026-01-27T12:30:00+00:00",
                }
            )
        )
        loaded = cache.load()
        assert loaded is not None
        assert loaded.groups == []
        assert loaded.fetched_at == datetime(2026, 1, 27, 12, 0, 0, tzinfo=UTC)
        assert loaded.last_attempt_at == datetime(2026, 1, 27, 12, 30, 0, tzinfo=UTC)

    def test_malformed_fetched_at_keeps_last_attempt(self, tmp_path):
        """`fetched_at` and `last_attempt_at` are independent keys — one bad value keeps the other."""
        cache = UsageCache(cache_dir=tmp_path)
        (tmp_path / "usage_limits.json").write_text(
            json.dumps(
                {
                    "data": {"groups": [{"key": "session", "overall": None, "models": []}]},
                    "fetched_at": "not-a-date",
                    "last_attempt_at": "2026-01-27T12:30:00+00:00",
                }
            )
        )
        loaded = cache.load()
        assert loaded is not None
        assert loaded.last_attempt_at == datetime(2026, 1, 27, 12, 30, 0, tzinfo=UTC)

    def test_scope_fields_survive_cache_roundtrip(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path)
        weekly = UsageGroup(key="weekly", window_hours=WEEKLY_WINDOW)
        weekly.models = [
            UsageLimit(label="Fable", utilization=10.0, resets_at=None, model="Fable"),
            UsageLimit(label="Fable·cli", utilization=70.0, resets_at=None, model="Fable", surface="cli"),
        ]
        cache.save(UsageData(groups=[weekly], fetched_at=datetime.now(UTC)))
        loaded = cache.load()
        assert loaded is not None
        restored = _group(loaded, "weekly")
        assert restored is not None
        assert [(m.label, m.model, m.surface) for m in restored.models] == [
            ("Fable", "Fable", None),
            ("Fable·cli", "Fable", "cli"),
        ]

    def test_cache_without_scope_fields_still_loads(self, tmp_path):
        """Caches written before scoped rows carried model/surface must not be rejected."""
        cache = UsageCache(cache_dir=tmp_path)
        (tmp_path / "usage_limits.json").write_text(
            json.dumps(
                {
                    "data": {
                        "groups": [
                            {
                                "key": "weekly",
                                "overall": {"label": "Weekly", "utilization": 42.0, "resets_at": None},
                                "models": [{"label": "Fable", "utilization": 5.0, "resets_at": None}],
                            }
                        ]
                    },
                    "fetched_at": "2026-01-27T12:00:00+00:00",
                }
            )
        )
        loaded = cache.load()
        assert loaded is not None
        weekly = _group(loaded, "weekly")
        assert weekly is not None
        assert [(m.label, m.model, m.surface) for m in weekly.models] == [("Fable", None, None)]

    def test_cache_limit_with_wrong_typed_fields_is_dropped(self, tmp_path):
        """A wrong-typed `label`/`utilization` must die here, not at render time.

        Neither `dict.get()` nor the dataclass constructor raises on a bad type, so such a value
        would sail past load()'s except block and only blow up later in `_visible_groups`
        (`label.casefold()`, `utilization > 0`) — outside any handler.
        """
        cache = UsageCache(cache_dir=tmp_path)
        (tmp_path / "usage_limits.json").write_text(
            json.dumps(
                {
                    "data": {
                        "groups": [
                            {
                                "key": "weekly",
                                "overall": {"label": "Weekly", "utilization": 42.0, "resets_at": None},
                                "models": [
                                    {"label": 12345, "utilization": 5.0, "resets_at": None},
                                    {"label": "Fable", "utilization": "not-a-number", "resets_at": None},
                                    {"label": "Opus", "utilization": 7.0, "resets_at": None},
                                ],
                            }
                        ]
                    },
                    "fetched_at": "2026-01-27T12:00:00+00:00",
                }
            )
        )
        loaded = cache.load()
        assert loaded is not None
        weekly = _group(loaded, "weekly")
        assert weekly is not None
        assert weekly.overall is not None
        assert weekly.overall.label == "Weekly"
        assert [m.label for m in weekly.models] == ["Opus"]

    def test_corrupt_cache_returns_none(self, tmp_path):
        """No usable timestamp at all -> None; a malformed payload with one -> timestamps only."""
        cache = UsageCache(cache_dir=tmp_path)
        cache_file = tmp_path / "usage_limits.json"

        # Neither timestamp is parseable -> nothing worth keeping.
        cache_file.write_text(
            json.dumps(
                {"data": {"groups": [{"key": "session", "overall": None, "models": []}]}, "fetched_at": "not-a-date"}
            )
        )
        assert cache.load() is None

        cache_file.write_text(json.dumps({"data": ["not", "a", "dict"], "fetched_at": "2026-01-27T12:00:00+00:00"}))
        loaded = cache.load()
        assert loaded is not None
        assert loaded.groups == []
        assert loaded.fetched_at == datetime(2026, 1, 27, 12, 0, 0, tzinfo=UTC)

        cache_file.write_text("{not json at all")
        assert cache.load() is None

    def test_retry_after_until_round_trips(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=60)
        until = datetime.now(UTC) + timedelta(seconds=1198)
        cache.save(UsageData(groups=[], fetched_at=datetime.now(UTC), retry_after_until=until))
        loaded = cache.load()
        assert loaded is not None
        assert loaded.retry_after_until == until

    def test_payload_round_trips(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=60)
        seen = datetime.now(UTC)
        reset = datetime.now(UTC) + timedelta(hours=3)
        cache.save(
            UsageData(
                groups=[],
                fetched_at=seen,
                payload=RateLimits(
                    five_hour=RateLimitWindow(46.0, reset),
                    seven_day=RateLimitWindow(15.0, None),
                ),
                payload_seen_at=seen,
            )
        )
        loaded = cache.load()
        assert loaded is not None
        assert loaded.payload is not None
        assert loaded.payload.five_hour is not None
        assert loaded.payload.five_hour.used_percentage == 46.0
        assert loaded.payload.five_hour.resets_at == reset
        assert loaded.payload.seven_day is not None
        assert loaded.payload.seven_day.resets_at is None
        assert loaded.payload_seen_at == seen

    def test_cache_without_the_new_keys_still_loads(self, tmp_path):
        """A file written by the previous version must keep working."""
        cache_file = tmp_path / "usage_limits.json"
        cache_file.write_text(
            json.dumps(
                {
                    "data": {"groups": [{"key": "weekly", "overall": None, "models": []}]},
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "last_attempt_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        loaded = UsageCache(cache_dir=tmp_path, rate_limit=60).load()
        assert loaded is not None
        assert loaded.retry_after_until is None
        assert loaded.payload is None
        assert loaded.payload_seen_at is None

    def test_malformed_new_keys_are_ignored(self, tmp_path):
        cache_file = tmp_path / "usage_limits.json"
        cache_file.write_text(
            json.dumps(
                {
                    "data": {"groups": []},
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "last_attempt_at": datetime.now(UTC).isoformat(),
                    "retry_after_until": "not a date",
                    "payload": "soon",
                    "payload_seen_at": 12345,
                }
            )
        )
        loaded = UsageCache(cache_dir=tmp_path, rate_limit=60).load()
        assert loaded is not None
        assert loaded.retry_after_until is None
        assert loaded.payload is None

    def test_oversized_integers_are_dropped_not_raised(self, tmp_path):
        """An int too large for a float drops the value instead of raising out of load()."""
        huge = 10**400
        cache_file = tmp_path / "usage_limits.json"
        cache_file.write_text(
            json.dumps(
                {
                    "data": {"groups": [{"key": "weekly", "overall": {"label": "Weekly", "utilization": huge}}]},
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "payload": {"five_hour": {"used_percentage": huge}},
                }
            )
        )
        loaded = UsageCache(cache_dir=tmp_path, rate_limit=60).load()
        assert loaded is not None
        weekly = _group(loaded, "weekly")
        assert weekly is not None
        assert weekly.overall is None
        assert loaded.payload is None

    def test_claim_attempt_writes_the_stamp_before_returning(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=60)
        before = datetime.now(UTC)
        claimed = cache.claim_attempt(None)
        on_disk = json.loads((tmp_path / "usage_limits.json").read_text())
        assert claimed.last_attempt_at is not None
        assert claimed.last_attempt_at >= before
        assert datetime.fromisoformat(on_disk["last_attempt_at"]) >= before

    def test_claim_attempt_keeps_existing_data(self, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=60)
        old = datetime.now(UTC) - timedelta(minutes=40)
        cache.save(UsageData(groups=[_weekly_group(2.0, None)], fetched_at=old, last_attempt_at=old))
        claimed = cache.claim_attempt(cache.load())
        assert claimed.fetched_at == old
        assert claimed.last_attempt_at is not None
        assert claimed.last_attempt_at > old
        loaded = cache.load()
        assert loaded is not None
        assert loaded.groups


class TestRenderMultiline:
    """Nested multiline rendering."""

    def test_session_and_weekly(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.5), seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Usage:" in output
        assert "Session:" in output
        assert "11%" in output
        assert "Weekly:" in output
        assert "2%" in output

    def test_models_nested_under_weekly(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.5), seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(
                        None,
                        None,
                        models=[
                            UsageLimit("Fable", 34.0, datetime.now(UTC) + timedelta(days=4)),
                            UsageLimit("Opus", 88.0, datetime.now(UTC) + timedelta(days=4)),
                        ],
                    )
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        lines = output.split("\n")
        # Fable/Opus lines are indented (nested under Weekly).
        fable_line = next(x for x in lines if "Fable" in x)
        assert fable_line.startswith("  ")
        assert "34%" in output
        assert "Opus:" in output
        assert "88%" in output

    def test_zero_percent_model_hidden_by_default(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.5), seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 0.0, None)])],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Fable" not in output

    def test_used_model_shown_by_default(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(
                        2.0,
                        datetime.now(UTC) + timedelta(days=3),
                        models=[UsageLimit("Fable", 5.0, datetime.now(UTC) + timedelta(days=4))],
                    )
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Fable" in output

    def test_models_top_level_when_overall_hidden(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(
                        None,
                        datetime.now(UTC) + timedelta(days=3),
                        models=[UsageLimit("Fable", 34.0, datetime.now(UTC) + timedelta(days=4))],
                    )
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        fable_line = next(line for line in output.split("\n") if "Fable" in line)
        assert not fable_line.startswith("  ")

    def test_dynamic_label_width_aligns(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(
                        2.0,
                        datetime.now(UTC) + timedelta(days=3),
                        models=[
                            UsageLimit("Claude Opus 4.1", 5.0, datetime.now(UTC) + timedelta(days=4)),
                        ],
                    )
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        # Long model name must not be truncated.
        assert output is not None
        assert "Claude Opus 4.1:" in output

    def test_returns_none_when_no_data(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = None
            assert UsageLimitsModule(ctx, {}).render() is None

    def test_render_none_when_all_hidden(self, make_render_context, minimal_input_data, tmp_path):
        """show_session=False, show_weekly=False, no models -> no bare 'Usage:' header."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _session_group(11.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    _weekly_group(2.0, datetime.now(UTC) + timedelta(days=3)),
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {"show_session": False, "show_weekly": False}).render()
        assert output is None

    def test_null_resets_at_shows_dash(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(2.0, datetime.now(UTC) + timedelta(days=3), models=[UsageLimit("Fable", 45.0, None)])
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Fable:" in output
        assert "(—)" in output

    def test_show_reset_time_false_hides_time_and_placeholder(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.5), seven_day=None)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 45.0, None)])],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {"show_reset_time": False}).render()
        assert output is not None
        assert "11%" in output
        assert "45%" in output
        # Neither the reset time of a timed row nor the "(—)" placeholder of an untimed one.
        assert "(" not in output

    def test_naive_resets_at_is_treated_as_utc(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        naive = (datetime.now(UTC) + timedelta(days=4)).replace(tzinfo=None)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 34.0, naive)])],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {"model_time_format": "remaining"}).render()
        assert output is not None
        assert "34%" in output
        assert "(—)" not in output


class TestRenderSingleLine:
    """Flat single-line rendering."""

    def test_flat_short_labels(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.5), seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _weekly_group(
                        None,
                        None,
                        models=[UsageLimit("Fable", 34.0, datetime.now(UTC) + timedelta(days=4))],
                    )
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {"multiline": False}).render()
        assert output is not None
        assert output.count("\n") == 0
        assert "5h" in output
        assert "7d" in output
        assert "Fable" in output


class TestProgressBar:
    def test_render_with_progress_bar(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(45.0, 2.5), seven_day=None)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
            output = UsageLimitsModule(ctx, {"show_progress_bar": True}).render()
        assert output is not None
        assert "[" in output
        assert "]" in output


class TestPayloadSource:
    """Session / Weekly come from the payload; per-model rows come from the API cache."""

    def test_overall_rows_come_from_the_payload(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            # The cache holds DIFFERENT overall numbers — the payload must win.
            mock_get.return_value = UsageData(
                groups=[_session_group(11.0, None), _weekly_group(2.0, None)],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "46%" in output
        assert "15%" in output
        assert "11%" not in output
        assert "2%" not in output

    def test_model_rows_come_from_the_cache(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 25.0, None)])],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Fable" in output
        assert "25%" in output

    def test_without_payload_or_cached_payload_no_overall_rows(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_session_group(11.0, None), _weekly_group(2.0, None)],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is None

    def test_model_rows_render_without_any_payload(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(2.0, None, models=[UsageLimit("Fable", 25.0, None)])],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Fable" in output
        assert "2%" not in output

    def test_cached_payload_is_used_when_the_block_is_absent(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[],
                fetched_at=datetime.now(UTC),
                payload=RateLimits(five_hour=RateLimitWindow(46.0, None), seven_day=None),
                payload_seen_at=datetime.now(UTC) - timedelta(minutes=2),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "46%" in output

    def test_payload_is_persisted_to_the_cache(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        with patch("statuskit.modules.usage_limits.get_token", return_value=None):
            UsageLimitsModule(ctx, {})._get_usage_data()
        cached = UsageCache(cache_dir=tmp_path, rate_limit=120).load()
        assert cached is not None
        assert cached.payload is not None
        assert cached.payload.five_hour is not None
        assert cached.payload.five_hour.used_percentage == 46.0
        assert cached.payload_seen_at is not None

    def test_payload_is_not_rewritten_within_the_save_interval(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch("statuskit.modules.usage_limits.get_token", return_value=None):
            UsageLimitsModule(ctx, {})._get_usage_data()
            first_cached = UsageCache(cache_dir=tmp_path, rate_limit=120).load()
            assert first_cached is not None
            first = first_cached.payload_seen_at
            UsageLimitsModule(ctx, {})._get_usage_data()
            second_cached = UsageCache(cache_dir=tmp_path, rate_limit=120).load()
            assert second_cached is not None
            second = second_cached.payload_seen_at
        assert first is not None
        assert first == second

    def test_show_session_false_hides_the_payload_row(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
            output = UsageLimitsModule(ctx, {"show_session": False}).render()
        assert output is not None
        assert "46%" not in output
        assert "15%" in output

    def test_persisting_the_payload_does_not_suppress_the_first_fetch(self, make_render_context, tmp_path):
        """Regression: a payload write on a cold cache must not read back as a completed attempt.

        `_persist_payload` fabricates a `UsageData` when there is no cache file yet. If that
        fabricated entry's `last_attempt_at` defaulted to `fetched_at` (as `UsageData` used to),
        the TTL gate right below would see an attempt "already made" moments ago and skip the
        fetch for a full `cache_ttl` — even though no request was ever sent.
        """
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            mock_fetch.return_value = FetchOutcome(
                data=UsageData(groups=[_weekly_group(2.0, None)], fetched_at=datetime.now(UTC))
            )
            UsageLimitsModule(ctx, {})._get_usage_data()
        mock_fetch.assert_called_once()

    def test_the_persisted_payload_does_not_throttle_a_sibling_session(self, make_render_context, tmp_path):
        """Regression: the cold-cache payload write must not stand a SIBLING session down either.

        The payload block is written to a cold cache before any attempt is made. A second module
        instance over that same cache dir must still attempt its own fetch — the fabricated entry
        on disk must not carry a `last_attempt_at` that throttles it. (A render with no token is no
        longer a way to get here: it claims the attempt, and a claim is meant to throttle.)
        """
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        UsageLimitsModule(ctx, {})._persist_payload(None)
        assert (tmp_path / "usage_limits.json").exists()

        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            mock_fetch.return_value = FetchOutcome(
                data=UsageData(groups=[_weekly_group(2.0, None)], fetched_at=datetime.now(UTC))
            )
            UsageLimitsModule(ctx, {})._get_usage_data()
        mock_fetch.assert_called_once()


class TestStaleness:
    """Rows rendered from a cache whose source failed to refresh carry their age."""

    def _stale_cache(self, models):
        """Endpoint cache whose last attempt failed 40 minutes after the last success.

        The extra second keeps the age clear of the `40m` / `39m` boundary: the renderer floors
        minutes, so an age of exactly 2400 s would be at the mercy of float rounding.
        """
        fetched = datetime.now(UTC) - timedelta(minutes=40, seconds=1)
        return UsageData(
            groups=[_weekly_group(None, None, models=models)],
            fetched_at=fetched,
            last_attempt_at=datetime.now(UTC),
        )

    def test_model_row_shows_its_age_when_the_refresh_failed(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._stale_cache([UsageLimit("Fable", 25.0, None)])
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "(40m ago)" in output

    def test_fresh_model_row_has_no_suffix(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        now = datetime.now(UTC)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 25.0, None)])],
                fetched_at=now,
                last_attempt_at=now,
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "ago)" not in output

    def test_successful_fetch_leaves_no_stale_suffix(self, make_render_context, minimal_input_data, tmp_path):
        """End-to-end: a real, successful fetch must not leave `fetched_at` behind `last_attempt_at`.

        `test_fresh_model_row_has_no_suffix` above only proves the renderer is correct once
        `fetched_at == last_attempt_at`; it hand-builds that state directly. Production never
        produced it before this fix: `_apply_outcome`'s success branch stamped `last_attempt_at`
        with a fresh `now` but left `fetched_at` at the earlier instant `parse_api_response` set
        inside `fetch_usage_api` — so `_display_data`'s `fetched_at < last_attempt_at` check was
        true immediately after every successful fetch, and every per-model row carried a permanent,
        ever-growing "(Xm ago)".
        """
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        with (
            patch("statuskit.modules.usage_limits.get_token") as mock_token,
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            mock_token.return_value = "test-token"
            mock_fetch.return_value = FetchOutcome(
                data=parse_api_response(make_api_response(models={"Fable": (25.0, None)}))
            )
            output = module.render()
        assert output is not None
        assert "ago)" not in output

    def test_live_payload_rows_never_show_an_age(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(46.0, 3.0), seven_day=(15.0, 60.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._stale_cache([])
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "46%" in output
        assert "ago)" not in output

    def test_cached_payload_rows_show_their_age(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[],
                fetched_at=datetime.now(UTC),
                last_attempt_at=datetime.now(UTC),
                payload=RateLimits(five_hour=RateLimitWindow(46.0, None), seven_day=None),
                payload_seen_at=datetime.now(UTC) - timedelta(minutes=5, seconds=1),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "(5m ago)" in output

    def test_suffix_appears_in_single_line_mode(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._stale_cache([UsageLimit("Fable", 25.0, None)])
            output = UsageLimitsModule(ctx, {"multiline": False}).render()
        assert output is not None
        assert "(40m ago)" in output

    def test_suffix_follows_the_reset_time(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        reset = datetime.now(UTC) + timedelta(days=2)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._stale_cache([UsageLimit("Fable", 25.0, reset)])
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert re.search(r"\(\w{3} \d{2}:\d{2}\) \(40m ago\)", output)

    def test_sub_minute_age_has_no_suffix(self, make_render_context, tmp_path):
        """Below the floor, `format_remaining_time` renders "0m" — suppress the suffix entirely."""
        ctx = _payload_ctx(make_render_context, tmp_path)
        fetched = datetime.now(UTC) - timedelta(seconds=30)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 25.0, None)])],
                fetched_at=fetched,
                last_attempt_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "ago)" not in output

    def _aged_cache(self, seconds: float) -> UsageData:
        """A per-model cache whose last refresh attempt failed `seconds` after the last success."""
        return UsageData(
            groups=[_weekly_group(None, None, models=[UsageLimit("Fable", 25.0, None)])],
            fetched_at=datetime.now(UTC) - timedelta(seconds=seconds),
            last_attempt_at=datetime.now(UTC),
        )

    def test_age_inside_the_refresh_cycle_has_no_suffix(self, make_render_context, tmp_path):
        """Past the minute floor but inside cache_ttl: the data is not due yet, so it is not late."""
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._aged_cache(61)
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "ago)" not in output

    def test_age_past_the_refresh_cycle_shows_the_suffix(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._aged_cache(121)  # default cache_ttl is 120
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "(2m ago)" in output

    def test_the_threshold_follows_cache_ttl(self, make_render_context, tmp_path):
        """The same age is late under a short TTL and not yet late under a long one."""
        ctx = _payload_ctx(make_render_context, tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._aged_cache(121)
            short = UsageLimitsModule(ctx, {"cache_ttl": 60}).render()
            mock_get.return_value = self._aged_cache(121)
            long_ttl = UsageLimitsModule(ctx, {"cache_ttl": 600}).render()
        assert short is not None
        assert long_ttl is not None
        assert "(2m ago)" in short
        assert "ago)" not in long_ttl


class TestGetUsageDataRateLimited:
    """Rate-limit / fetch-first behavior (unchanged logic, grouped data)."""

    def test_returns_cached_when_rate_limited(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        # `last_attempt_at` is explicit here — `fetched_at` alone no longer implies "just
        # attempted" (see TestDataModel::test_usage_data_leaves_last_attempt_at_none_when_omitted),
        # and this test's whole point is proving the TTL gate blocks the fetch below.
        module.cache.save(
            UsageData(
                groups=[_session_group(45.0, datetime.now(UTC) + timedelta(hours=2.5))],
                fetched_at=datetime.now(UTC),
                last_attempt_at=datetime.now(UTC),
            )
        )
        with (
            patch("statuskit.modules.usage_limits.get_token") as mock_token,
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            mock_token.return_value = "test-token"
            result = module._get_usage_data()
        mock_fetch.assert_not_called()
        assert result is not None
        session = _group(result, "session")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 45.0

    def test_fetches_first_when_allowed(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        module.cache.save(
            UsageData(
                groups=[_session_group(10.0, datetime.now(UTC) + timedelta(hours=2))],
                fetched_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        new_data = UsageData(
            groups=[_session_group(50.0, datetime.now(UTC) + timedelta(hours=2))],
            fetched_at=datetime.now(UTC),
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome(data=new_data)
                result = module._get_usage_data()
        assert result is not None
        session = _group(result, "session")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 50.0

    def test_empty_parse_is_kept_and_noted_in_debug(self, make_render_context, minimal_input_data, tmp_path):
        """A fetch that parses no limits must NOT silently fall back to the cache.

        Falling back would render a stale-but-plausible statusline and hide the fact that the API
        changed shape — the user would never learn statuskit needs updating. Keep the empty
        result, and say why in debug output.
        """
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        module.cache.save(
            UsageData(
                groups=[_session_group(10.0, datetime.now(UTC) + timedelta(hours=2))],
                fetched_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome(data=UsageData(groups=[], fetched_at=datetime.now(UTC)))
                result = module._get_usage_data()
        assert result is not None
        assert result.groups == []  # empty result kept, cache NOT used as a cover-up
        assert any("parsed no limits" in m for m in module._debug_messages)

        # ...but the empty payload must NOT be written over the last known-good cache: a later
        # render that legitimately falls back (no token / rate limited / API down) would then get
        # the poisoned empty data long after this hiccup passed.
        reloaded = module.cache.load()
        assert reloaded is not None
        session = _group(reloaded, "session")
        assert session is not None
        assert session.overall is not None
        assert session.overall.utilization == 10.0

    def test_empty_parse_still_throttles_when_no_cache_exists(self, make_render_context, minimal_input_data, tmp_path):
        """With no cache to protect, the empty payload IS persisted — it carries the attempt clock.

        Otherwise nothing records that an attempt happened and the failing API is re-hit on every
        render (the throttle bug from the previous round, one branch over).
        """
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome(data=UsageData(groups=[], fetched_at=datetime.now(UTC)))
                module._get_usage_data()
        reloaded = module.cache.load()
        assert reloaded is not None
        assert reloaded.last_attempt_at is not None

    def test_empty_parse_still_renders_the_cached_payload(self, make_render_context, minimal_input_data, tmp_path):
        """A 200-that-parsed-nothing must not blank out Session/Weekly sourced from the cache.

        Regression: `_apply_outcome`'s empty-parse branch used to drop `payload` / `payload_seen_at`
        from the `UsageData` it handed back to `render()`, while every other branch (success, and
        every failure) carried the cached payload across. Inside the TTL, gate 3 in
        `_get_usage_data` already returns the cached entry with its payload untouched — so to the
        user, Session/Weekly blinked out once every `cache_ttl` for a reason that has nothing to do
        with where those rows come from.
        """
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        module.cache.save(
            UsageData(
                groups=[],
                fetched_at=datetime.now(UTC),
                payload=RateLimits(five_hour=RateLimitWindow(46.0, None), seven_day=None),
                payload_seen_at=datetime.now(UTC),
            )
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome(data=UsageData(groups=[], fetched_at=datetime.now(UTC)))
                output = module.render()
        assert output is not None
        assert "46%" in output

    def test_throttles_after_failed_fetch(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        module.cache.save(
            UsageData(
                groups=[_session_group(45.0, datetime.now(UTC) + timedelta(hours=2))],
                fetched_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome()
                module._get_usage_data()
                module._get_usage_data()
        assert mock_fetch.call_count == 1

    def test_failed_fetch_advances_attempt_clock_but_not_fetched_at(
        self, make_render_context, minimal_input_data, tmp_path
    ):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        stale = datetime.now(UTC) - timedelta(days=5)
        module.cache.save(
            UsageData(
                groups=[_session_group(45.0, datetime.now(UTC) + timedelta(hours=2))],
                fetched_at=stale,
            )
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            with patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch:
                mock_fetch.return_value = FetchOutcome()
                module._get_usage_data()
        reloaded = module.cache.load()
        assert reloaded is not None
        assert reloaded.fetched_at == stale
        assert reloaded.last_attempt_at is not None
        assert reloaded.last_attempt_at > stale

    def test_debug_output_in_render(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path, debug=True)
        module = UsageLimitsModule(ctx, {})
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = None
            output = module.render()
        assert output is not None
        assert "[usage_limits] No token" in output

    def test_429_persists_the_backoff_deadline(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch(
                "statuskit.modules.usage_limits.fetch_usage_api",
                return_value=FetchOutcome(status=429, retry_after=1198.0),
            ),
        ):
            UsageLimitsModule(ctx, {})._get_usage_data()
        cached = UsageCache(cache_dir=tmp_path, rate_limit=120).load()
        assert cached is not None
        assert cached.retry_after_until is not None
        assert 1100 < (cached.retry_after_until - datetime.now(UTC)).total_seconds() <= 1198

    def test_huge_retry_after_is_capped_end_to_end(self, make_render_context, minimal_input_data, tmp_path):
        """Regression: a finite but huge Retry-After overflowed `now + timedelta(...)`.

        The OverflowError escaped `_apply_outcome` and the whole module vanished from the
        statusline. Only `urlopen` is mocked, so the real header parsing is on the path.
        """
        headers = Message()
        headers["Retry-After"] = "1000000000000"
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen,
        ):
            mock_urlopen.side_effect = HTTPError(url=API_URL, code=429, msg="rate", hdrs=headers, fp=None)
            UsageLimitsModule(ctx, {})._get_usage_data()
        cached = UsageCache(cache_dir=tmp_path, rate_limit=120).load()
        assert cached is not None
        assert cached.retry_after_until is not None
        assert (cached.retry_after_until - datetime.now(UTC)).total_seconds() <= RETRY_AFTER_MAX

    def test_backoff_blocks_the_next_request(self, make_render_context, minimal_input_data, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=0)
        cache.save(
            UsageData(
                groups=[_weekly_group(2.0, None)],
                fetched_at=datetime.now(UTC) - timedelta(minutes=40),
                last_attempt_at=datetime.now(UTC) - timedelta(minutes=40),
                retry_after_until=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            module = UsageLimitsModule(ctx, {"cache_ttl": 0})
            data = module._get_usage_data()
        mock_fetch.assert_not_called()
        assert data is not None
        assert data.groups
        assert any("Backing off" in m for m in module._debug_messages)

    def test_expired_backoff_allows_the_request(self, make_render_context, minimal_input_data, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=0)
        cache.save(
            UsageData(
                groups=[],
                fetched_at=datetime.now(UTC) - timedelta(minutes=40),
                last_attempt_at=datetime.now(UTC) - timedelta(minutes=40),
                retry_after_until=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch(
                "statuskit.modules.usage_limits.fetch_usage_api",
                return_value=FetchOutcome(
                    data=UsageData(groups=[_weekly_group(3.0, None)], fetched_at=datetime.now(UTC))
                ),
            ) as mock_fetch,
        ):
            UsageLimitsModule(ctx, {"cache_ttl": 0})._get_usage_data()
        mock_fetch.assert_called_once()

    def test_backoff_beyond_the_cap_is_ignored(self, make_render_context, minimal_input_data, tmp_path):
        """A deadline further than RETRY_AFTER_MAX away was never written by a capped 429.

        It comes from a cache that predates the cap, or a corrupted one; honouring it would stall
        refreshes indefinitely.
        """
        cache = UsageCache(cache_dir=tmp_path, rate_limit=0)
        cache.save(
            UsageData(
                groups=[],
                fetched_at=datetime.now(UTC) - timedelta(minutes=40),
                last_attempt_at=datetime.now(UTC) - timedelta(minutes=40),
                retry_after_until=datetime(9999, 12, 31, tzinfo=UTC),
            )
        )
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch(
                "statuskit.modules.usage_limits.fetch_usage_api",
                return_value=FetchOutcome(
                    data=UsageData(groups=[_weekly_group(3.0, None)], fetched_at=datetime.now(UTC))
                ),
            ) as mock_fetch,
        ):
            UsageLimitsModule(ctx, {"cache_ttl": 0})._get_usage_data()
        mock_fetch.assert_called_once()

    def test_success_clears_the_backoff(self, make_render_context, minimal_input_data, tmp_path):
        cache = UsageCache(cache_dir=tmp_path, rate_limit=0)
        cache.save(
            UsageData(
                groups=[],
                fetched_at=datetime.now(UTC) - timedelta(minutes=40),
                last_attempt_at=datetime.now(UTC) - timedelta(minutes=40),
                retry_after_until=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch(
                "statuskit.modules.usage_limits.fetch_usage_api",
                return_value=FetchOutcome(
                    data=UsageData(groups=[_weekly_group(3.0, None)], fetched_at=datetime.now(UTC))
                ),
            ),
        ):
            UsageLimitsModule(ctx, {"cache_ttl": 0})._get_usage_data()
        reloaded = UsageCache(cache_dir=tmp_path, rate_limit=0).load()
        assert reloaded is not None
        assert reloaded.retry_after_until is None

    def test_attempt_is_claimed_before_the_request(self, make_render_context, minimal_input_data, tmp_path):
        seen: dict = {}

        def fake_fetch(_token):
            seen["stamp"] = json.loads((tmp_path / "usage_limits.json").read_text()).get("last_attempt_at")
            return FetchOutcome(error="timeout")

        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.fetch_usage_api", side_effect=fake_fetch),
        ):
            UsageLimitsModule(ctx, {"cache_ttl": 0})._get_usage_data()
        assert seen["stamp"] is not None

    def test_ttl_blocked_render_skips_the_token_lookup(self, make_render_context, minimal_input_data, tmp_path):
        """The lookup is a Keychain subprocess on macOS; a render the TTL blocks must not pay for it."""
        cache = UsageCache(cache_dir=tmp_path, rate_limit=120)
        cache.save(
            UsageData(
                groups=[_weekly_group(2.0, None)],
                fetched_at=datetime.now(UTC),
                last_attempt_at=datetime.now(UTC),
            )
        )
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            UsageLimitsModule(ctx, {})._get_usage_data()
        mock_token.assert_not_called()

    def test_token_is_looked_up_after_the_claim(self, make_render_context, minimal_input_data, tmp_path):
        """Keeps the load-to-claim window down to a file read and write.

        Sibling sessions that load the same stale stamp inside that window all pass the TTL; with the
        Keychain subprocess inside it, the window was ~17 ms instead of ~0.2 ms.
        """
        seen: dict = {}

        def fake_token():
            path = tmp_path / "usage_limits.json"
            seen["stamp"] = json.loads(path.read_text()).get("last_attempt_at") if path.exists() else None

        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch("statuskit.modules.usage_limits.get_token", side_effect=fake_token):
            UsageLimitsModule(ctx, {})._get_usage_data()
        assert seen["stamp"] is not None

    def test_missing_token_counts_as_a_failed_attempt(self, make_render_context, minimal_input_data, tmp_path):
        """A missing token claims the attempt like any failed fetch; a sibling stands down for the TTL."""
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch("statuskit.modules.usage_limits.get_token", return_value=None):
            UsageLimitsModule(ctx, {})._get_usage_data()
        with (
            patch("statuskit.modules.usage_limits.get_token", return_value="t"),
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
        ):
            UsageLimitsModule(ctx, {})._get_usage_data()
        mock_fetch.assert_not_called()

    def test_debug_message_when_claim_write_fails(self, make_render_context, minimal_input_data, tmp_path):
        """A claim write that never reaches disk must be visible in debug output.

        `UsageCache.save()` swallows `OSError`; without this, a non-writable cache directory
        silently disables the attempt-claim coordination and the thundering herd it exists to
        prevent comes back with no diagnostic.
        """
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path, debug=True)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        with (
            patch("statuskit.modules.usage_limits.get_token") as mock_token,
            patch("statuskit.modules.usage_limits.fetch_usage_api") as mock_fetch,
            patch.object(Path, "replace", side_effect=OSError("disk full")),
        ):
            mock_token.return_value = "test-token"
            mock_fetch.return_value = FetchOutcome()
            output = module.render()
        assert output is not None
        assert "Could not write the attempt claim" in output

    def test_debug_message_names_the_failure(self, make_render_context, minimal_input_data, tmp_path):
        cases = [
            (FetchOutcome(status=401), "HTTP 401"),
            (FetchOutcome(status=503), "HTTP 503"),
            (FetchOutcome(error="timeout"), "timeout"),
            (FetchOutcome(error="network error"), "network error"),
            (FetchOutcome(status=429, retry_after=60.0), "HTTP 429"),
        ]
        # Each case gets its own cache dir: the 429 case persists a backoff deadline, which
        # would gate every case that ran after it and make the test pass only in this order.
        for i, (outcome, expected) in enumerate(cases):
            ctx = make_render_context(minimal_input_data, cache_dir=tmp_path / str(i), debug=True)
            with (
                patch("statuskit.modules.usage_limits.get_token", return_value="t"),
                patch("statuskit.modules.usage_limits.fetch_usage_api", return_value=outcome),
            ):
                module = UsageLimitsModule(ctx, {"cache_ttl": 0})
                module._get_usage_data()
            assert any(expected in m for m in module._debug_messages), (outcome, module._debug_messages)


def test_cache_ttl_default_flows_to_cache(make_render_context, minimal_input_data, tmp_path):
    ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
    module = UsageLimitsModule(ctx, {})
    assert module.cache is not None
    assert module.cache.rate_limit == 120


def test_cache_ttl_custom_flows_to_cache(make_render_context, minimal_input_data, tmp_path):
    ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
    module = UsageLimitsModule(ctx, {"cache_ttl": 120})
    assert module.cache is not None
    assert module.cache.rate_limit == 120


class TestModelVisibilityConfig:
    """models_always_show / models_never_show overrides."""

    @staticmethod
    def _data_with_fable(util: float, resets_at: datetime | None):
        # No group overall here — an overall row now comes from the payload (see `_payload_ctx`
        # in each test), not from the API cache these tests mock.
        return UsageData(
            groups=[_weekly_group(None, None, models=[UsageLimit("Fable", util, resets_at)])],
            fetched_at=datetime.now(UTC),
        )

    def test_always_show_forces_zero_percent_model(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(0.0, None)
            output = UsageLimitsModule(ctx, {"models_always_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" in output

    def test_never_show_hides_used_model(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_never_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    def test_never_beats_always(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_always_show": ["Fable"], "models_never_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    def test_matching_is_case_insensitive(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_never_show": ["fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    @staticmethod
    def _data_with_scoped_fable():
        """Weekly models: the model-wide Fable row and a narrower Fable·cli one (no overall)."""
        resets = datetime.now(UTC) + timedelta(days=4)
        return UsageData(
            groups=[
                _weekly_group(
                    None,
                    None,
                    models=[
                        UsageLimit("Fable", 34.0, resets, model="Fable"),
                        UsageLimit("Fable·cli", 12.0, resets, model="Fable", surface="cli"),
                    ],
                )
            ],
            fetched_at=datetime.now(UTC),
        )

    def test_bare_model_name_covers_its_scoped_rows(self, make_render_context, tmp_path):
        """An existing `fable` config entry keeps covering the narrower Fable·cli row."""
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_scoped_fable()
            output = UsageLimitsModule(ctx, {"models_never_show": ["fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    def test_bare_model_name_in_always_show_also_forces_scoped_rows(self, make_render_context, tmp_path):
        """Documented consequence of symmetric matching: `always_show` widens the same way.

        A bare `Fable` entry force-shows a 0% `Fable·cli` row the user never configured. Kept
        symmetric with `never_show` on purpose — a new scoped row from the API should surface
        rather than stay invisible — so this asserts the surprising direction stays intentional.
        """
        data = UsageData(
            groups=[
                _weekly_group(
                    None,
                    None,
                    models=[
                        UsageLimit("Fable", 0.0, None, model="Fable"),
                        UsageLimit("Fable·cli", 0.0, None, model="Fable", surface="cli"),
                    ],
                )
            ],
            fetched_at=datetime.now(UTC),
        )
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = data
            output = UsageLimitsModule(ctx, {"models_always_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable·cli" in output

    def test_scoped_name_targets_only_that_row(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=None, seven_day=(2.0, 72.0))
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_scoped_fable()
            output = UsageLimitsModule(ctx, {"models_never_show": ["fable·cli"]}).render()
        assert output is not None
        assert "Fable·cli" not in output
        assert "Fable" in output


class TestConfigBackCompat:
    """Old configs with removed keys must not crash."""

    def test_legacy_show_sonnet_key_does_not_crash(self, make_render_context, tmp_path):
        ctx = _payload_ctx(make_render_context, tmp_path, five_hour=(11.0, 2.0), seven_day=None)
        # show_sonnet / sonnet_time_format were removed; they are now unknown keys.
        config = {"show_sonnet": True, "sonnet_time_format": "reset_at"}
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
            module = UsageLimitsModule(ctx, config)
            output = module.render()
        assert output is not None
        assert "Session:" in output
        # Removed keys fall back to defaults, not applied.
        assert not hasattr(module.params, "show_sonnet")

    def test_cache_ttl_defaults_to_120(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.params.cache_ttl == 120
        assert module.cache is not None
        assert module.cache.rate_limit == 120
