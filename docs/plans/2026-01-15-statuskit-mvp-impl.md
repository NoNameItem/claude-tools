# StatusKit MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement minimal working statuskit with core infrastructure and model module.

**Architecture:** Modular statusline kit - parse JSON from Claude Code, load configured modules, render output. Each module is a class with `render() -> str | None` method.

**Tech Stack:** Python 3.11+, termcolor, tomllib (stdlib), dataclasses (stdlib)

---

## Task 1: Add termcolor dependency

**Files:**
- Modify: `packages/statuskit/pyproject.toml:6`

**Step 1: Update pyproject.toml**

Change line 6 from:
```toml
dependencies = []
```
to:
```toml
dependencies = ["termcolor"]
```

**Step 2: Sync dependencies**

Run: `uv sync`
Expected: Success, termcolor installed

**Step 3: Stage changes**

```bash
git add packages/statuskit/pyproject.toml
```

---

## Task 2: Create test factories and fixtures

**Files:**
- Create: `packages/statuskit/tests/factories/__init__.py`
- Create: `packages/statuskit/tests/factories/core.py`
- Create: `packages/statuskit/tests/conftest.py`

**Step 1: Create factories package init**

```python
# packages/statuskit/tests/factories/__init__.py
"""Test data factories for statuskit.

Usage in tests:
    from tests.factories import make_model_data, make_input_data

    # or import specific module
    from tests.factories.core import make_context_window_data
"""

from .core import (
    make_context_window_data,
    make_cost_data,
    make_input_data,
    make_model_data,
)

__all__ = [
    "make_context_window_data",
    "make_cost_data",
    "make_input_data",
    "make_model_data",
]
```

**Step 2: Create core factories (pure functions, no pytest)**

```python
# packages/statuskit/tests/factories/core.py
"""Core data factories for statuskit tests.

Pure functions that create test data dicts.
No pytest dependency - can be imported directly.
"""


def make_model_data(
    display_name: str = "Opus",
    model_id: str | None = None,
) -> dict:
    """Create model data dict."""
    data = {"display_name": display_name}
    if model_id:
        data["id"] = model_id
    return data


def make_cost_data(
    duration_ms: int | None = None,
    cost_usd: float | None = None,
    api_duration_ms: int | None = None,
    lines_added: int | None = None,
    lines_removed: int | None = None,
) -> dict:
    """Create cost data dict."""
    data = {}
    if duration_ms is not None:
        data["total_duration_ms"] = duration_ms
    if cost_usd is not None:
        data["total_cost_usd"] = cost_usd
    if api_duration_ms is not None:
        data["total_api_duration_ms"] = api_duration_ms
    if lines_added is not None:
        data["total_lines_added"] = lines_added
    if lines_removed is not None:
        data["total_lines_removed"] = lines_removed
    return data


def make_context_window_data(
    size: int = 200000,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
) -> dict:
    """Create context window data dict."""
    return {
        "context_window_size": size,
        "current_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
    }


def make_input_data(
    model: dict | None = None,
    cost: dict | None = None,
    context_window: dict | None = None,
    session_id: str | None = None,
    cwd: str | None = None,
    workspace: dict | None = None,
) -> dict:
    """Create full input data dict."""
    data = {}
    if model is not None:
        data["model"] = model
    if cost is not None:
        data["cost"] = cost
    if context_window is not None:
        data["context_window"] = context_window
    if session_id is not None:
        data["session_id"] = session_id
    if cwd is not None:
        data["cwd"] = cwd
    if workspace is not None:
        data["workspace"] = workspace
    return data
```

**Step 3: Create conftest.py with pytest fixtures only**

```python
# packages/statuskit/tests/conftest.py
"""Pytest fixtures for statuskit tests.

Fixtures use factories from tests.factories package.
Keep this file lean - only pytest-specific code.
"""

import pytest

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
# Typed factory fixtures (require types module, added in Task 3)
# =============================================================================
# These will be added after core/types.py is created:
# - make_status_input: factory fixture to create StatusInput from dict
# - make_render_context: factory fixture to create RenderContext
```

**Step 4: Stage changes**

```bash
git add packages/statuskit/tests/factories/ packages/statuskit/tests/conftest.py
```

---

## Task 3: Create core/types.py — Data types

**Files:**
- Create: `packages/statuskit/src/statuskit/core/__init__.py`
- Create: `packages/statuskit/src/statuskit/core/types.py`
- Modify: `packages/statuskit/tests/conftest.py` (add factory fixtures)
- Test: `packages/statuskit/tests/test_types.py`

**Step 1: Create core package init**

```python
# packages/statuskit/src/statuskit/core/__init__.py
"""Core statuskit infrastructure."""
```

**Step 2: Write failing test for StatusInput.from_dict**

```python
# packages/statuskit/tests/test_types.py
"""Tests for statuskit.core.types."""

from statuskit.core.types import StatusInput


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
    assert result.model.id == "claude-opus-4-1"
    assert result.model.display_name == "Opus"
    assert result.workspace.current_dir == "/home/user"
    assert result.workspace.project_dir == "/home/user/project"
    assert result.cost.total_duration_ms == 45000
    assert result.context_window.context_window_size == 200000
    assert result.context_window.current_usage.input_tokens == 8500


def test_status_input_from_dict_empty():
    """Parse empty JSON."""
    result = StatusInput.from_dict({})

    assert result.model is None
    assert result.session_id is None
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_types.py -v`
Expected: FAIL with ImportError (module not found)

**Step 4: Write types.py implementation**

```python
# packages/statuskit/src/statuskit/core/types.py
"""Data types for statuskit."""

from dataclasses import dataclass


@dataclass
class Model:
    """Model information from Claude Code."""

    id: str | None
    display_name: str


@dataclass
class Workspace:
    """Workspace paths from Claude Code."""

    current_dir: str
    project_dir: str


@dataclass
class Cost:
    """Cost and timing information from Claude Code."""

    total_cost_usd: float | None
    total_duration_ms: int | None
    total_api_duration_ms: int | None
    total_lines_added: int | None
    total_lines_removed: int | None


@dataclass
class CurrentUsage:
    """Current context window usage."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass
class ContextWindow:
    """Context window information from Claude Code."""

    context_window_size: int | None
    total_input_tokens: int | None
    total_output_tokens: int | None
    current_usage: CurrentUsage | None


@dataclass
class StatusInput:
    """Parsed input from Claude Code status hook."""

    session_id: str | None
    cwd: str | None
    model: Model | None
    workspace: Workspace | None
    cost: Cost | None
    context_window: ContextWindow | None

    @classmethod
    def from_dict(cls, data: dict) -> "StatusInput":
        """Parse JSON dict into StatusInput dataclass.

        Missing fields become None.
        """
        model_data = data.get("model")
        model = (
            Model(
                id=model_data.get("id"),
                display_name=model_data.get("display_name", "Unknown"),
            )
            if model_data
            else None
        )

        workspace_data = data.get("workspace")
        workspace = (
            Workspace(
                current_dir=workspace_data.get("current_dir", ""),
                project_dir=workspace_data.get("project_dir", ""),
            )
            if workspace_data
            else None
        )

        cost_data = data.get("cost")
        cost = (
            Cost(
                total_cost_usd=cost_data.get("total_cost_usd"),
                total_duration_ms=cost_data.get("total_duration_ms"),
                total_api_duration_ms=cost_data.get("total_api_duration_ms"),
                total_lines_added=cost_data.get("total_lines_added"),
                total_lines_removed=cost_data.get("total_lines_removed"),
            )
            if cost_data
            else None
        )

        ctx_data = data.get("context_window")
        context_window = None
        if ctx_data:
            usage_data = ctx_data.get("current_usage")
            current_usage = (
                CurrentUsage(
                    input_tokens=usage_data.get("input_tokens", 0),
                    output_tokens=usage_data.get("output_tokens", 0),
                    cache_creation_input_tokens=usage_data.get(
                        "cache_creation_input_tokens", 0
                    ),
                    cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
                )
                if usage_data
                else None
            )

            context_window = ContextWindow(
                context_window_size=ctx_data.get("context_window_size"),
                total_input_tokens=ctx_data.get("total_input_tokens"),
                total_output_tokens=ctx_data.get("total_output_tokens"),
                current_usage=current_usage,
            )

        return cls(
            session_id=data.get("session_id"),
            cwd=data.get("cwd"),
            model=model,
            workspace=workspace,
            cost=cost,
            context_window=context_window,
        )


@dataclass
class RenderContext:
    """Context passed to modules for rendering."""

    debug: bool
    data: StatusInput
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_types.py -v`
Expected: 3 tests PASS

**Step 6: Add factory fixtures to conftest.py**

Append to `packages/statuskit/tests/conftest.py`:

```python
# =============================================================================
# Factory fixtures (now that types module exists)
# =============================================================================

from statuskit.core.types import RenderContext, StatusInput


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
```

**Step 7: Stage changes**

```bash
git add packages/statuskit/src/statuskit/core/ packages/statuskit/tests/
```

---

## Task 4: Create core/config.py — Configuration

**Files:**
- Create: `packages/statuskit/src/statuskit/core/config.py`
- Test: `packages/statuskit/tests/test_config.py`

**Step 1: Write failing test for load_config**

```python
# packages/statuskit/tests/test_config.py
"""Tests for statuskit.core.config."""

from pathlib import Path
from unittest.mock import patch

from statuskit.core.config import Config, load_config


def test_config_defaults():
    """Config has sensible defaults."""
    cfg = Config()

    assert cfg.debug is False
    assert cfg.modules == ["model", "git", "beads", "quota"]
    assert cfg.module_configs == {}


def test_config_get_module_config_missing():
    """get_module_config returns empty dict for missing module."""
    cfg = Config()
    assert cfg.get_module_config("model") == {}


def test_config_get_module_config_present():
    """get_module_config returns module config when present."""
    cfg = Config(module_configs={"model": {"show_duration": False}})
    assert cfg.get_module_config("model") == {"show_duration": False}


def test_load_config_no_file(tmp_path: Path):
    """load_config returns defaults when config file missing."""
    with patch("statuskit.core.config.CONFIG_PATH", tmp_path / "nonexistent.toml"):
        cfg = load_config()

    assert cfg.debug is False
    assert cfg.modules == ["model", "git", "beads", "quota"]


def test_load_config_with_file(tmp_path: Path):
    """load_config parses TOML file."""
    config_file = tmp_path / "statuskit.toml"
    config_file.write_text("""
debug = true
modules = ["model", "quota"]

[model]
show_duration = false
context_format = "bar"
""")

    with patch("statuskit.core.config.CONFIG_PATH", config_file):
        cfg = load_config()

    assert cfg.debug is True
    assert cfg.modules == ["model", "quota"]
    assert cfg.get_module_config("model") == {
        "show_duration": False,
        "context_format": "bar",
    }


def test_load_config_invalid_toml(tmp_path: Path, capsys):
    """load_config shows error and returns defaults for invalid TOML."""
    config_file = tmp_path / "statuskit.toml"
    config_file.write_text("invalid toml [[[")

    with patch("statuskit.core.config.CONFIG_PATH", config_file):
        cfg = load_config()

    # Should return defaults
    assert cfg.debug is False
    # Should print error
    captured = capsys.readouterr()
    assert "[!] Config error:" in captured.out
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_config.py -v`
Expected: FAIL with ImportError

**Step 3: Write config.py implementation**

```python
# packages/statuskit/src/statuskit/core/config.py
"""Configuration loading for statuskit."""

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from termcolor import colored

CONFIG_PATH = Path.home() / ".claude" / "statuskit.toml"


@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    modules: list[str] = field(
        default_factory=lambda: ["model", "git", "beads", "quota"]
    )
    module_configs: dict[str, dict] = field(default_factory=dict)

    def get_module_config(self, name: str) -> dict:
        """Get configuration for a specific module."""
        return self.module_configs.get(name, {})


def load_config() -> Config:
    """Load configuration from TOML file.

    Returns defaults if file doesn't exist.
    Shows error and returns defaults if file is invalid.
    """
    if not CONFIG_PATH.exists():
        return Config()

    try:
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        # Always show config errors
        print(colored(f"[!] Config error: {e}", "red"))
        return Config()

    # Extract module configs (any dict that's not a top-level setting)
    module_configs = {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and k not in ("debug", "modules")
    }

    return Config(
        debug=data.get("debug", False),
        modules=data.get("modules", Config().modules),
        module_configs=module_configs,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_config.py -v`
Expected: 6 tests PASS

**Step 5: Stage changes**

```bash
git add packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
```

---

## Task 5: Create modules/base.py — Base module class

**Files:**
- Create: `packages/statuskit/src/statuskit/modules/__init__.py`
- Create: `packages/statuskit/src/statuskit/modules/base.py`
- Test: `packages/statuskit/tests/test_base_module.py`

**Step 1: Write failing test for BaseModule**

```python
# packages/statuskit/tests/test_base_module.py
"""Tests for statuskit.modules.base."""

from statuskit.modules.base import BaseModule


class TestModule(BaseModule):
    """Concrete test implementation of BaseModule."""

    name = "test"
    description = "Test module"

    def render(self) -> str | None:
        return f"test output debug={self.debug}"


def test_base_module_init(make_render_context, minimal_input_data):
    """BaseModule stores context and config."""
    ctx = make_render_context(minimal_input_data, debug=True)
    config = {"option": "value"}

    mod = TestModule(ctx, config)

    assert mod.debug is True
    assert mod.data is ctx.data
    assert mod.config == {"option": "value"}


def test_base_module_render(make_render_context):
    """BaseModule subclass can render."""
    ctx = make_render_context({}, debug=False)

    mod = TestModule(ctx, {})
    result = mod.render()

    assert result == "test output debug=False"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_base_module.py -v`
Expected: FAIL with ImportError

**Step 3: Create modules package init**

```python
# packages/statuskit/src/statuskit/modules/__init__.py
"""Statuskit modules."""

from statuskit.core.types import RenderContext
from statuskit.modules.base import BaseModule

__all__ = ["BaseModule", "RenderContext"]
```

**Step 4: Write base.py implementation**

```python
# packages/statuskit/src/statuskit/modules/base.py
"""Base module class for statuskit."""

from abc import ABC, abstractmethod

from statuskit.core.types import RenderContext


class BaseModule(ABC):
    """Base class for statuskit modules.

    Subclasses must define:
    - name: str - module identifier
    - description: str - human-readable description
    - render() -> str | None - output to display
    """

    name: str
    description: str

    def __init__(self, ctx: RenderContext, config: dict):
        """Initialize module with context and config.

        Args:
            ctx: Render context with debug flag and status data
            config: Module-specific configuration from TOML
        """
        self.debug = ctx.debug
        self.data = ctx.data
        self.config = config

    @abstractmethod
    def render(self) -> str | None:
        """Render module output.

        Returns:
            String to display (can be multiline) or None to skip.
        """
        ...
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_base_module.py -v`
Expected: 2 tests PASS

**Step 6: Stage changes**

```bash
git add packages/statuskit/src/statuskit/modules/ packages/statuskit/tests/test_base_module.py
```

---

## Task 6: Create modules/model.py — Model module

**Files:**
- Create: `packages/statuskit/src/statuskit/modules/model.py`
- Test: `packages/statuskit/tests/test_model_module.py`

**Step 1: Write failing test for ModelModule**

```python
# packages/statuskit/tests/test_model_module.py
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

        assert "2h" not in result
        assert "[Test]" in result

    def test_render_context_free_format(self, make_render_context):
        """Context shows free tokens in default format."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "free"})
        result = mod.render()

        assert "Context:" in result
        assert "150,000 free" in result
        assert "75.0%" in result

    def test_render_context_used_format(self, make_render_context):
        """Context shows used tokens."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "used"})
        result = mod.render()

        assert "50,000 used" in result
        assert "25.0%" in result

    def test_render_context_ratio_format(self, make_render_context):
        """Context shows used/total ratio."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "ratio"})
        result = mod.render()

        assert "50,000/200,000" in result

    def test_render_context_bar_format(self, make_render_context):
        """Context shows progress bar."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_format": "bar"})
        result = mod.render()

        assert "[" in result
        assert "█" in result
        assert "75%" in result

    def test_render_context_compact(self, make_render_context):
        """Context shows compact numbers."""
        data = make_input_data(
            model=make_model_data(),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {"show_context": True, "context_compact": True})
        result = mod.render()

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

        assert "150,000 free" in result

    def test_render_full_output(self, make_render_context):
        """Full output has all parts."""
        data = make_input_data(
            model=make_model_data(display_name="Opus"),
            cost=make_cost_data(duration_ms=8100000),
            context_window=make_context_window_data(
                size=200000, input_tokens=50000, output_tokens=1000
            ),
        )
        ctx = make_render_context(data)
        mod = ModelModule(ctx, {})
        result = mod.render()

        assert "[Opus]" in result
        assert "2h 15m" in result
        assert "Context:" in result
        assert " | " in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_model_module.py -v`
Expected: FAIL with ImportError

**Step 3: Write model.py implementation**

```python
# packages/statuskit/src/statuskit/modules/model.py
"""Model module for statuskit."""

from termcolor import colored

from statuskit.modules.base import BaseModule


class ModelModule(BaseModule):
    """Display model name, session duration, and context window usage."""

    name = "model"
    description = "Model name, session duration, context window usage"

    def __init__(self, ctx, config: dict):
        super().__init__(ctx, config)
        self.show_duration = config.get("show_duration", True)
        self.show_context = config.get("show_context", True)
        self.context_format = config.get("context_format", "free")
        self.context_compact = config.get("context_compact", False)
        self.threshold_green = config.get("context_threshold_green", 50)
        self.threshold_yellow = config.get("context_threshold_yellow", 25)

    def render(self) -> str | None:
        parts = []

        # [Model name]
        if self.data.model:
            parts.append(f"[{self.data.model.display_name}]")

        # Duration: 2h 15m
        if self.show_duration:
            duration = self._format_duration()
            if duration:
                parts.append(duration)

        # Context: 150,000 free (75.0%)
        if self.show_context:
            ctx_str = self._format_context()
            if ctx_str:
                parts.append(f"Context: {ctx_str}")

        return " | ".join(parts) if parts else None

    def _format_duration(self) -> str | None:
        if not self.data.cost or not self.data.cost.total_duration_ms:
            return None

        ms = self.data.cost.total_duration_ms
        if ms == 0:
            return None

        total_sec = ms // 1000
        if total_sec < 60:
            return f"{total_sec}s"

        hours, remainder = divmod(total_sec, 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _format_context(self) -> str | None:
        ctx = self.data.context_window
        if not ctx or not ctx.current_usage or not ctx.context_window_size:
            return None

        usage = ctx.current_usage
        total = ctx.context_window_size
        used = (
            usage.input_tokens
            + usage.cache_creation_input_tokens
            + usage.cache_read_input_tokens
        )
        free = total - used
        pct_free = (free / total) * 100
        pct_used = (used / total) * 100

        # Determine color based on free percentage
        if pct_free > self.threshold_green:
            color = "green"
        elif pct_free > self.threshold_yellow:
            color = "yellow"
        else:
            color = "red"

        # Format numbers
        if self.context_compact:
            free_fmt = self._compact_number(free)
            used_fmt = self._compact_number(used)
            total_fmt = self._compact_number(total)
            pct_fmt = (
                f"{pct_free:.0f}%"
                if self.context_format == "free"
                else f"{pct_used:.0f}%"
            )
        else:
            free_fmt = f"{free:,}"
            used_fmt = f"{used:,}"
            total_fmt = f"{total:,}"
            pct_fmt = (
                f"{pct_free:.1f}%"
                if self.context_format == "free"
                else f"{pct_used:.1f}%"
            )

        # Format output based on style
        if self.context_format == "free":
            text = f"{free_fmt} free ({pct_fmt})"
        elif self.context_format == "used":
            text = f"{used_fmt} used ({pct_fmt})"
        elif self.context_format == "ratio":
            pct_fmt = f"{pct_used:.0f}%" if self.context_compact else f"{pct_used:.1f}%"
            text = f"{used_fmt}/{total_fmt} ({pct_fmt})"
        elif self.context_format == "bar":
            bar = self._make_bar(pct_free)
            text = f"{bar} {pct_free:.0f}%"
        else:
            text = f"{free_fmt} free ({pct_fmt})"

        return colored(text, color)

    def _compact_number(self, n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}k"
        return str(n)

    def _make_bar(self, pct_free: float, width: int = 10) -> str:
        filled = int(pct_free / 100 * width)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_model_module.py -v`
Expected: All tests PASS

**Step 5: Stage changes**

```bash
git add packages/statuskit/src/statuskit/modules/model.py packages/statuskit/tests/test_model_module.py
```

---

## Task 7: Create core/loader.py — Module loader

**Files:**
- Create: `packages/statuskit/src/statuskit/core/loader.py`
- Test: `packages/statuskit/tests/test_loader.py`

**Step 1: Write failing test for load_modules**

```python
# packages/statuskit/tests/test_loader.py
"""Tests for statuskit.core.loader."""

from statuskit.core.loader import load_modules
from statuskit.core.config import Config
from statuskit.modules.model import ModelModule


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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_loader.py -v`
Expected: FAIL with ImportError

**Step 3: Write loader.py implementation**

```python
# packages/statuskit/src/statuskit/core/loader.py
"""Module loader for statuskit."""

from statuskit.core.config import Config
from statuskit.core.types import RenderContext
from statuskit.modules.base import BaseModule
from statuskit.modules import model

BUILTIN_MODULES: dict[str, type[BaseModule]] = {
    "model": model.ModelModule,
    # "git": ...,    # v0.2
    # "beads": ...,  # v0.3
    # "quota": ...,  # v0.4
}


def load_modules(config: Config, ctx: RenderContext) -> list[BaseModule]:
    """Load modules based on configuration.

    Args:
        config: Statuskit configuration
        ctx: Render context for modules

    Returns:
        List of instantiated modules
    """
    modules = []
    for name in config.modules:
        if name in BUILTIN_MODULES:
            module_config = config.get_module_config(name)
            modules.append(BUILTIN_MODULES[name](ctx, module_config))
        elif ctx.debug:
            print(f"[!] Unknown module: {name}")
    return modules
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_loader.py -v`
Expected: 4 tests PASS

**Step 5: Stage changes**

```bash
git add packages/statuskit/src/statuskit/core/loader.py packages/statuskit/tests/test_loader.py
```

---

## Task 8: Update __init__.py — Entry point

**Files:**
- Modify: `packages/statuskit/src/statuskit/__init__.py`
- Test: `packages/statuskit/tests/test_main.py`

**Step 1: Write failing test for main**

```python
# packages/statuskit/tests/test_main.py
"""Tests for statuskit entry point."""

import json
from io import StringIO
from unittest.mock import patch

from statuskit import main


def test_main_tty_shows_usage(capsys):
    """main shows usage when stdin is tty."""
    with patch("sys.stdin.isatty", return_value=True):
        main()

    captured = capsys.readouterr()
    assert "statuskit:" in captured.out
    assert "stdin" in captured.out


def test_main_parses_json_and_renders(capsys):
    """main parses JSON and renders output."""
    input_data = {
        "model": {"display_name": "Opus"},
        "cost": {"total_duration_ms": 60000},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 50000,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }

    stdin = StringIO(json.dumps(input_data))
    stdin.isatty = lambda: False

    with patch("sys.stdin", stdin):
        main()

    captured = capsys.readouterr()
    assert "[Opus]" in captured.out


def test_main_invalid_json_silent(capsys):
    """main silently exits on invalid JSON (non-debug)."""
    stdin = StringIO("not json")
    stdin.isatty = lambda: False

    with patch("sys.stdin", stdin):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""


def test_main_empty_json_no_output(capsys):
    """main produces no output for empty JSON."""
    stdin = StringIO("{}")
    stdin.isatty = lambda: False

    with patch("sys.stdin", stdin):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_main.py -v`
Expected: FAIL (current main just prints "placeholder")

**Step 3: Update __init__.py with full implementation**

```python
# packages/statuskit/src/statuskit/__init__.py
"""Modular statusline kit for Claude Code."""

import json
import sys

from termcolor import colored

from .core.config import load_config
from .core.loader import load_modules
from .core.types import RenderContext, StatusInput


def main() -> None:
    """Entry point for statuskit command."""
    # 1. Check stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        return

    # 2. Load config
    config = load_config()

    # 3. Read data from Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # 4. Create context
    ctx = RenderContext(debug=config.debug, data=data)

    # 5. Load modules
    modules = load_modules(config, ctx)

    # 6. Render modules
    for mod in modules:
        try:
            output = mod.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                print(colored(f"[!] {mod.name}: {e}", "red"))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_main.py -v`
Expected: 4 tests PASS

**Step 5: Stage changes**

```bash
git add packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
```

---

## Task 9: Clean up and run full test suite

**Files:**
- Delete: `packages/statuskit/tests/test_placeholder.py`

**Step 1: Delete placeholder test**

Run: `rm packages/statuskit/tests/test_placeholder.py`

**Step 2: Run full test suite**

Run: `uv run pytest packages/statuskit/tests/ -v`
Expected: All tests PASS

**Step 3: Run linting**

Run: `uv run ruff check packages/statuskit/`
Expected: No errors

**Step 4: Run type checking**

Run: `uv run ty check packages/statuskit/`
Expected: No errors (or manageable warnings)

**Step 5: Manual integration test**

Run:
```bash
echo '{"model":{"display_name":"Test"},"cost":{"total_duration_ms":3600000},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000,"output_tokens":500,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}' | uv run statuskit
```
Expected: `[Test] | 1h 0m | Context: 199,000 free (99.5%)` (with green color)

---

## Summary

После выполнения всех задач statuskit MVP будет включать:

- `core/types.py` — парсинг JSON от Claude Code в dataclasses
- `core/config.py` — загрузка TOML конфигурации
- `core/loader.py` — загрузка модулей по конфигу
- `modules/base.py` — BaseModule ABC
- `modules/model.py` — отображение модели, длительности, контекста
- `__init__.py` — main() entry point

Тесты покрывают все компоненты. Готово к использованию как Claude Code status hook.
