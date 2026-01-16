"""Tests for statuskit.modules.base."""

from statuskit.modules.base import BaseModule


class StubModule(BaseModule):
    """Stub implementation of BaseModule for testing."""

    name = "stub"
    description = "Stub module"

    def render(self) -> str | None:
        return f"stub output debug={self.debug}"


def test_base_module_init(make_render_context, minimal_input_data):
    """BaseModule stores context and config."""
    ctx = make_render_context(minimal_input_data, debug=True)
    config = {"option": "value"}

    mod = StubModule(ctx, config)

    assert mod.debug is True
    assert mod.data is ctx.data
    assert mod.config == {"option": "value"}


def test_base_module_render(make_render_context):
    """BaseModule subclass can render."""
    ctx = make_render_context({}, debug=False)

    mod = StubModule(ctx, {})
    result = mod.render()

    assert result == "stub output debug=False"
