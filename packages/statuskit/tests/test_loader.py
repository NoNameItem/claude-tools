"""Tests for statuskit.core.loader."""

from statuskit.core.config import Config
from statuskit.core.loader import BUILTIN_MODULES, load_modules
from statuskit.modules.git import GitModule
from statuskit.modules.model import ModelModule
from statuskit.modules.usage_limits import UsageLimitsModule


def test_git_module_registered():
    """Git module is registered in BUILTIN_MODULES."""
    assert "git" in BUILTIN_MODULES
    assert BUILTIN_MODULES["git"] is GitModule


def test_load_modules_builtin(make_render_context, minimal_input_data):
    """load_modules loads builtin modules."""
    config = Config(modules=["model"])
    ctx = make_render_context(minimal_input_data)

    modules = load_modules(config, ctx)

    assert len(modules) == 1
    assert isinstance(modules[0], ModelModule)


def test_load_modules_unknown_silent(make_render_context, minimal_input_data):
    """load_modules silently skips unknown modules."""
    config = Config(modules=["model", "unknown"])
    ctx = make_render_context(minimal_input_data, debug=False)

    modules = load_modules(config, ctx)

    assert len(modules) == 1


def test_load_modules_unknown_debug(make_render_context, minimal_input_data, capsys):
    """load_modules prints warning for unknown modules in debug mode."""
    config = Config(modules=["unknown"])
    ctx = make_render_context(minimal_input_data, debug=True)

    modules = load_modules(config, ctx)

    assert len(modules) == 0
    captured = capsys.readouterr()
    assert "[!] Unknown module: unknown" in captured.out


def test_load_modules_with_config(make_render_context, minimal_input_data):
    """load_modules passes module config to modules."""
    config = Config(
        modules=["model"],
        module_configs={"model": {"show_duration": False}},
    )
    ctx = make_render_context(minimal_input_data)

    modules = load_modules(config, ctx)

    assert modules[0].config == {"show_duration": False}


def test_loads_usage_limits_module(make_render_context, minimal_input_data):
    """Loader includes usage_limits module."""
    config = Config(modules=["usage_limits"])
    ctx = make_render_context(minimal_input_data)

    modules = load_modules(config, ctx)

    assert len(modules) == 1
    assert isinstance(modules[0], UsageLimitsModule)
