"""Tests for statuskit.modules.model."""

from statuskit.modules.model import ModelModule

from .factories import (
    make_context_window_data,
    make_cost_data,
    make_input_data,
    make_model_data,
)


class TestModelModule:
    """Tests for ModelModule."""

    def test_render_model_name(self, make_render_context):
        """Render shows model display name."""
        data = make_input_data(model=make_model_data(display_name="Opus"))
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {})
        result = mod.render()

        assert result is not None
        assert "[Opus]" in result

    def test_render_no_model(self, make_render_context):
        """Render returns None when no model."""
        ctx = make_render_context({})
        mod = ModelModule(ctx, {})
        result = mod.render()

        assert result is None

    def test_render_duration_seconds(self, make_render_context):
        """Duration shows seconds for short sessions."""
        data = make_input_data(
            model=make_model_data(),
            cost=make_cost_data(duration_ms=45000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_duration": True})
        result = mod.render()

        assert result is not None
        assert "45s" in result

    def test_render_duration_minutes(self, make_render_context):
        """Duration shows minutes for longer sessions."""
        data = make_input_data(
            model=make_model_data(),
            cost=make_cost_data(duration_ms=180000),  # 3 minutes
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_duration": True})
        result = mod.render()

        assert result is not None
        assert "3m" in result

    def test_render_duration_hours(self, make_render_context):
        """Duration shows hours and minutes for long sessions."""
        data = make_input_data(
            model=make_model_data(),
            cost=make_cost_data(duration_ms=8100000),  # 2h 15m
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_duration": True})
        result = mod.render()

        assert result is not None
        assert "2h 15m" in result

    def test_render_duration_disabled(self, make_render_context):
        """Duration can be disabled."""
        data = make_input_data(
            model=make_model_data(display_name="Test"),
            cost=make_cost_data(duration_ms=8100000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_duration": False})
        result = mod.render()

        assert result is not None
        assert "2h" not in result
        assert "[Test]" in result

    def test_render_context_free_format(self, make_render_context):
        """Context shows free tokens in default format."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "free"})
        result = mod.render()

        assert result is not None
        assert "Context:" in result
        assert "150,000 free" in result
        assert "75.0%" in result

    def test_render_context_used_format(self, make_render_context):
        """Context shows used tokens."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "used"})
        result = mod.render()

        assert result is not None
        assert "50,000 used" in result
        assert "25.0%" in result

    def test_render_context_ratio_format(self, make_render_context):
        """Context shows used/total ratio."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "ratio"})
        result = mod.render()

        assert result is not None
        assert "50,000/200,000" in result

    def test_render_context_bar_format(self, make_render_context):
        """Context shows progress bar."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "bar"})
        result = mod.render()

        assert result is not None
        assert "[" in result
        assert "█" in result
        assert "75%" in result

    def test_render_context_compact(self, make_render_context):
        """Context shows compact numbers."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_compact": True})
        result = mod.render()

        assert result is not None
        assert "150k free" in result

    def test_render_context_disabled(self, make_render_context):
        """Context can be disabled."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(size=200000, input_tokens=50000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": False})
        result = mod.render()

        assert result is not None
        assert "Context" not in result

    def test_context_includes_cache_tokens(self, make_render_context):
        """Used tokens include cache tokens."""
        # used = 10000 + 20000 + 20000 = 50000
        # free = 200000 - 50000 = 150000
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000,
                input_tokens=10000,
                output_tokens=1000,
                cache_creation=20000,
                cache_read=20000,
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "free"})
        result = mod.render()

        assert result is not None
        assert "150,000 free" in result

    def test_render_full_output(self, make_render_context):
        """Full output has all parts."""
        data = make_input_data(
            model=make_model_data(display_name="Opus"),
            cost=make_cost_data(duration_ms=8100000),
            context_window=make_context_window_data(size=200000, input_tokens=50000, output_tokens=1000),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {})
        result = mod.render()

        assert result is not None
        assert "[Opus]" in result
        assert "2h 15m" in result
        assert "Context:" in result
        assert " | " in result
