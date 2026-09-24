"""Tests for statuskit.core.types."""

from statuskit.core.models import StatusInput

from tests.factories import make_input_data, make_rate_limits_data


def test_status_input_from_dict_minimal(minimal_input_data):
    """Parse minimal JSON with just model."""
    result = StatusInput.from_dict(minimal_input_data)

    assert result.model is not None
    assert result.model.display_name == "Opus"
    assert result.model.id is None
    assert result.session_id is None
    assert result.workspace is None
    assert result.cost is None
    assert result.context_window is None


def test_status_input_from_dict_full(full_input_data):
    """Parse full JSON with all fields."""
    result = StatusInput.from_dict(full_input_data)

    assert result.session_id == "abc123"
    assert result.cwd == "/home/user"
    assert result.model is not None
    assert result.model.id == "claude-opus-4-1"
    assert result.model.display_name == "Opus"
    assert result.workspace is not None
    assert result.workspace.current_dir == "/home/user"
    assert result.workspace.project_dir == "/home/user/project"
    assert result.cost is not None
    assert result.cost.total_duration_ms == 45000
    assert result.context_window is not None
    assert result.context_window.context_window_size == 200000
    assert result.context_window.current_usage is not None
    assert result.context_window.current_usage.input_tokens == 8500


def test_status_input_from_dict_empty():
    """Parse empty JSON."""
    result = StatusInput.from_dict({})

    assert result.model is None
    assert result.session_id is None


class TestRateLimitsParsing:
    """`rate_limits` block of the statusline payload."""

    def test_both_windows_parsed(self):
        data = make_input_data(
            rate_limits=make_rate_limits_data(five_hour=(46.0, 1757809800), seven_day=(15.0, 1758000000))
        )
        result = StatusInput.from_dict(data)
        assert result.rate_limits is not None
        assert result.rate_limits.five_hour is not None
        assert result.rate_limits.five_hour.used_percentage == 46.0
        assert result.rate_limits.five_hour.resets_at is not None
        assert result.rate_limits.five_hour.resets_at.timestamp() == 1757809800
        assert result.rate_limits.five_hour.resets_at.tzinfo is not None
        assert result.rate_limits.seven_day is not None
        assert result.rate_limits.seven_day.used_percentage == 15.0

    def test_missing_block_is_none(self):
        assert StatusInput.from_dict(make_input_data()).rate_limits is None

    def test_one_window_missing(self):
        data = make_input_data(rate_limits=make_rate_limits_data(five_hour=(46.0, 1757809800), seven_day=None))
        result = StatusInput.from_dict(data)
        assert result.rate_limits is not None
        assert result.rate_limits.five_hour is not None
        assert result.rate_limits.seven_day is None

    def test_window_without_reset_time(self):
        data = make_input_data(rate_limits=make_rate_limits_data(five_hour=(46.0, None), seven_day=None))
        result = StatusInput.from_dict(data)
        assert result.rate_limits is not None
        assert result.rate_limits.five_hour is not None
        assert result.rate_limits.five_hour.resets_at is None

    def test_unusable_percentage_drops_the_window(self):
        # 10**400: json.loads() builds such an int from a long literal, and it overflows float().
        for bad in (True, "46", None, float("nan"), float("inf"), [1], 10**400):
            data = make_input_data(rate_limits={"five_hour": {"used_percentage": bad, "resets_at": 1757809800}})
            assert StatusInput.from_dict(data).rate_limits is None

    def test_unusable_reset_time_keeps_the_window(self):
        for bad in (True, "later", {"a": 1}, float("nan"), 10**400):
            data = make_input_data(rate_limits={"five_hour": {"used_percentage": 46, "resets_at": bad}})
            result = StatusInput.from_dict(data)
            assert result.rate_limits is not None
            window = result.rate_limits.five_hour
            assert window is not None
            assert window.used_percentage == 46.0
            assert window.resets_at is None

    def test_non_dict_block_is_ignored(self):
        for bad in ("yes", 1, [], {"five_hour": "soon"}):
            assert StatusInput.from_dict(make_input_data(rate_limits=bad)).rate_limits is None

    def test_spend_limit_is_ignored(self):
        data = make_input_data(
            rate_limits={
                "five_hour": {"used_percentage": 46, "resets_at": 1757809800},
                "spend_limit": {"used_percentage": 80, "resets_at": 1758000000},
            }
        )
        result = StatusInput.from_dict(data)
        assert result.rate_limits is not None
        assert result.rate_limits.five_hour is not None
        assert not hasattr(result.rate_limits, "spend_limit")
