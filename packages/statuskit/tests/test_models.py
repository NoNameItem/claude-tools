"""Tests for statuskit.core.types."""

from statuskit.core.models import StatusInput


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
