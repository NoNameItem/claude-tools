"""Pytest fixtures for statuskit tests.

Fixtures use factories from tests.factories package.
Keep this file lean - only pytest-specific code.
"""

import pytest
from statuskit.core.models import RenderContext, StatusInput

from .factories import (
    make_context_window_data,
    make_cost_data,
    make_input_data,
    make_model_data,
)

# =============================================================================
# Preset fixtures (common test scenarios)
# =============================================================================


@pytest.fixture
def minimal_input_data() -> dict:
    """Minimal valid input with just model."""
    return make_input_data(model=make_model_data())


@pytest.fixture
def full_input_data() -> dict:
    """Full input with all fields populated."""
    return make_input_data(
        session_id="abc123",
        cwd="/home/user",
        model=make_model_data(display_name="Opus", model_id="claude-opus-4-1"),
        workspace={"current_dir": "/home/user", "project_dir": "/home/user/project"},
        cost=make_cost_data(
            duration_ms=45000,
            cost_usd=0.01,
            api_duration_ms=2300,
            lines_added=100,
            lines_removed=50,
        ),
        context_window=make_context_window_data(
            size=200000,
            input_tokens=8500,
            output_tokens=1200,
            cache_creation=5000,
            cache_read=2000,
        ),
    )


@pytest.fixture
def context_window_75pct_free() -> dict:
    """Context window data: 75% free (50k used of 200k)."""
    return make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000)


@pytest.fixture
def context_window_with_cache() -> dict:
    """Context window with cache tokens: 75% free."""
    return make_context_window_data(
        size=200000,
        input_tokens=10000,
        output_tokens=1000,
        cache_creation=20000,
        cache_read=20000,
    )


# =============================================================================
# Factory fixtures (now that types module exists)
# =============================================================================


@pytest.fixture
def make_status_input():
    """Factory fixture to create StatusInput from dict."""

    def _make(data: dict) -> StatusInput:
        return StatusInput.from_dict(data)

    return _make


@pytest.fixture
def make_render_context(make_status_input):
    """Factory fixture to create RenderContext."""

    def _make(data: dict, debug: bool = False) -> RenderContext:
        return RenderContext(debug=debug, data=make_status_input(data))

    return _make
