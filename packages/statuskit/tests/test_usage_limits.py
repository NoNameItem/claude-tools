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
    UsageGroup,
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

    def test_usage_data_defaults_last_attempt_to_fetched(self):
        now = datetime.now(UTC)
        data = UsageData(groups=[], fetched_at=now)
        assert data.last_attempt_at == now


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
        # A scoped limit that is not model-scoped (e.g. a future surface-scoped one) is
        # neither the group's scope-less overall nor a per-model limit -> ignore it.
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
        assert weekly.models == []

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

    def test_non_dict_response_yields_no_groups(self):
        # json.loads() can hand back a list or a string; the parser must degrade, not raise.
        assert parse_api_response(["not", "a", "dict"]).groups == []

    def test_legacy_keys_with_non_dict_values_are_skipped(self):
        # `x or {}` lets a truthy non-dict through; the following .get() would raise.
        response = {"five_hour": "unavailable", "seven_day": 0, "seven_day_sonnet": ["nope"]}
        assert parse_api_response(response).groups == []

    def test_scoped_non_model_limit_alone_yields_no_group(self):
        # With no scope-less entry, a lone surface-scoped item must not become the overall.
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
        data = parse_api_response(response)
        assert _group(data, "weekly") is None

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
    def test_format_weekday_time(self):
        result = format_reset_at(datetime(2026, 1, 29, 17, 0, 0, tzinfo=UTC))
        assert len(result.split()) == 2
        assert ":" in result


class TestFormatProgressBar:
    def test_empty_bar(self):
        assert format_progress_bar(0.0, width=10) == "[░░░░░░░░░░]"

    def test_full_bar(self):
        assert format_progress_bar(100.0, width=10) == "[██████████]"

    def test_half_bar(self):
        assert format_progress_bar(50.0, width=10) == "[█████░░░░░]"


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
    def test_fetch_success(self):
        response_data = json.dumps(make_api_response()).encode()
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_response = mock_urlopen.return_value.__enter__.return_value
            mock_response.read.return_value = response_data
            data = fetch_usage_api("test-token")
            assert data is not None
            session = _group(data, "session")
            assert session is not None
            assert session.overall is not None
            assert session.overall.utilization == 11.0

    def test_fetch_timeout(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError("timeout")
            assert fetch_usage_api("test-token") is None

    def test_fetch_error(self):
        with patch("statuskit.modules.usage_limits.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("connection failed")
            assert fetch_usage_api("test-token") is None


def _session_group(util: float, resets_at: datetime | None) -> UsageGroup:
    return UsageGroup("session", SESSION_WINDOW, overall=UsageLimit("Session", util, resets_at))


def _weekly_group(util: float | None, resets_at: datetime | None, models: list[UsageLimit] | None = None) -> UsageGroup:
    overall = UsageLimit("Weekly", util, resets_at) if util is not None else None
    return UsageGroup("weekly", WEEKLY_WINDOW, overall=overall, models=models or [])


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


class TestRenderMultiline:
    """Nested multiline rendering."""

    def test_session_and_weekly(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _session_group(11.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    _weekly_group(2.0, datetime.now(UTC) + timedelta(days=3)),
                ],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {}).render()
        assert output is not None
        assert "Usage:" in output
        assert "Session:" in output
        assert "11%" in output
        assert "Weekly:" in output
        assert "2%" in output

    def test_models_nested_under_weekly(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _session_group(11.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    _weekly_group(
                        2.0,
                        datetime.now(UTC) + timedelta(days=3),
                        models=[
                            UsageLimit("Fable", 34.0, datetime.now(UTC) + timedelta(days=4)),
                            UsageLimit("Opus", 88.0, datetime.now(UTC) + timedelta(days=4)),
                        ],
                    ),
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

    def test_zero_percent_model_hidden_by_default(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _session_group(11.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    _weekly_group(2.0, datetime.now(UTC) + timedelta(days=3), models=[UsageLimit("Fable", 0.0, None)]),
                ],
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


class TestRenderSingleLine:
    """Flat single-line rendering."""

    def test_flat_short_labels(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[
                    _session_group(11.0, datetime.now(UTC) + timedelta(hours=2.5)),
                    _weekly_group(
                        2.0,
                        datetime.now(UTC) + timedelta(days=3),
                        models=[UsageLimit("Fable", 34.0, datetime.now(UTC) + timedelta(days=4))],
                    ),
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
    def test_render_with_progress_bar(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_session_group(45.0, datetime.now(UTC) + timedelta(hours=2.5))],
                fetched_at=datetime.now(UTC),
            )
            output = UsageLimitsModule(ctx, {"show_progress_bar": True}).render()
        assert output is not None
        assert "[" in output
        assert "]" in output


class TestGetUsageDataRateLimited:
    """Rate-limit / fetch-first behavior (unchanged logic, grouped data)."""

    def test_returns_cached_when_rate_limited(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        module = UsageLimitsModule(ctx, {})
        assert module.cache is not None
        module.cache.save(
            UsageData(
                groups=[_session_group(45.0, datetime.now(UTC) + timedelta(hours=2.5))],
                fetched_at=datetime.now(UTC),
            )
        )
        with patch("statuskit.modules.usage_limits.get_token") as mock_token:
            mock_token.return_value = "test-token"
            result = module._get_usage_data()
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
                mock_fetch.return_value = new_data
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
                mock_fetch.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
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
                mock_fetch.return_value = UsageData(groups=[], fetched_at=datetime.now(UTC))
                module._get_usage_data()
        reloaded = module.cache.load()
        assert reloaded is not None
        assert reloaded.last_attempt_at is not None

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
                mock_fetch.return_value = None
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
                mock_fetch.return_value = None
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


def test_cache_ttl_default_flows_to_cache(make_render_context, minimal_input_data, tmp_path):
    ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
    module = UsageLimitsModule(ctx, {})
    assert module.cache is not None
    assert module.cache.rate_limit == 60


def test_cache_ttl_custom_flows_to_cache(make_render_context, minimal_input_data, tmp_path):
    ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
    module = UsageLimitsModule(ctx, {"cache_ttl": 120})
    assert module.cache is not None
    assert module.cache.rate_limit == 120


class TestModelVisibilityConfig:
    """models_always_show / models_never_show overrides."""

    @staticmethod
    def _data_with_fable(util: float, resets_at: datetime | None):
        return UsageData(
            groups=[
                _weekly_group(2.0, datetime.now(UTC) + timedelta(days=3), models=[UsageLimit("Fable", util, resets_at)])
            ],
            fetched_at=datetime.now(UTC),
        )

    def test_always_show_forces_zero_percent_model(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(0.0, None)
            output = UsageLimitsModule(ctx, {"models_always_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" in output

    def test_never_show_hides_used_model(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_never_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    def test_never_beats_always(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_always_show": ["Fable"], "models_never_show": ["Fable"]}).render()
        assert output is not None
        assert "Fable" not in output

    def test_matching_is_case_insensitive(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = self._data_with_fable(34.0, datetime.now(UTC) + timedelta(days=4))
            output = UsageLimitsModule(ctx, {"models_never_show": ["fable"]}).render()
        assert output is not None
        assert "Fable" not in output


class TestConfigBackCompat:
    """Old configs with removed keys must not crash."""

    def test_legacy_show_sonnet_key_does_not_crash(self, make_render_context, minimal_input_data, tmp_path):
        ctx = make_render_context(minimal_input_data, cache_dir=tmp_path)
        # show_sonnet / sonnet_time_format were removed; they are now unknown keys.
        config = {"show_sonnet": True, "sonnet_time_format": "reset_at"}
        with patch.object(UsageLimitsModule, "_get_usage_data") as mock_get:
            mock_get.return_value = UsageData(
                groups=[_session_group(11.0, datetime.now(UTC) + timedelta(hours=2))],
                fetched_at=datetime.now(UTC),
            )
            module = UsageLimitsModule(ctx, config)
            output = module.render()
        assert output is not None
        assert "Session:" in output
        # Removed keys fall back to defaults, not applied.
        assert not hasattr(module.params, "show_sonnet")
