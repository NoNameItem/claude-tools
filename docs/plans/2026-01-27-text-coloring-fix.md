# Text Coloring Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix ANSI color output in statuskit when called from Claude Code hooks (non-TTY stdout).

**Architecture:** Add `colors` config option (default: True). When enabled, set `FORCE_COLOR=1` environment variable before termcolor calls.

**Tech Stack:** Python, termcolor, pytest

---

## Task 1: Add `colors` field to Config

**Files:**
- Modify: `packages/statuskit/src/statuskit/core/config.py:24-30`
- Test: `packages/statuskit/tests/test_config.py`

**Step 1: Write the failing test for Config.colors default**

Add to `test_config.py`:

```python
def test_config_colors_default_true():
    """Config.colors defaults to True."""
    cfg = Config()
    assert cfg.colors is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_config.py::test_config_colors_default_true -v`
Expected: FAIL with "AttributeError: 'Config' object has no attribute 'colors'"

**Step 3: Add colors field to Config dataclass**

In `config.py`, modify the Config dataclass:

```python
@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    colors: bool = True
    modules: list[str] = field(default_factory=lambda: ["model", "git", "beads", "quota"])
    module_configs: dict[str, dict] = field(default_factory=dict)
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_DIR)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_config.py::test_config_colors_default_true -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff format packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
uv run ruff check --fix packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
uv run ty check
git add packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
git commit -m "feat(statuskit): add colors field to Config dataclass"
```

---

## Task 2: Parse `colors` from TOML config

**Files:**
- Modify: `packages/statuskit/src/statuskit/core/config.py:66-71`
- Test: `packages/statuskit/tests/test_config.py`

**Step 1: Write the failing test for colors=false in config**

Add to `test_config.py`:

```python
def test_load_config_colors_false(tmp_path: Path, monkeypatch):
    """load_config parses colors=false from TOML."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    config_file = home / ".claude" / "statuskit.toml"
    config_file.write_text("colors = false")

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.colors is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_config.py::test_load_config_colors_false -v`
Expected: FAIL with "AssertionError: assert True is False"

**Step 3: Parse colors in load_config()**

In `config.py`, modify the return statement in `load_config()`:

```python
            return Config(
                debug=data.get("debug", False),
                colors=data.get("colors", True),
                modules=data.get("modules", Config().modules),
                module_configs=module_configs,
                cache_dir=cache_dir,
            )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_config.py::test_load_config_colors_false -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff format packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
uv run ruff check --fix packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
uv run ty check
git add packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
git commit -m "feat(statuskit): parse colors option from TOML config"
```

---

## Task 3: Set FORCE_COLOR environment variable

**Files:**
- Modify: `packages/statuskit/src/statuskit/__init__.py:1-5, 76-88`
- Test: `packages/statuskit/tests/test_main.py`

**Step 1: Write the failing test for FORCE_COLOR being set**

Add to `test_main.py`:

```python
def test_render_statusline_sets_force_color(monkeypatch):
    """_render_statusline sets FORCE_COLOR=1 when colors enabled."""
    import os
    from statuskit import _render_statusline
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Remove FORCE_COLOR if present
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {"model": {"display_name": "Test"}}
    mock_config = Config(modules=["model"], colors=True)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        _render_statusline()

    assert os.environ.get("FORCE_COLOR") == "1"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/statuskit/tests/test_main.py::test_render_statusline_sets_force_color -v`
Expected: FAIL with "AssertionError: assert None == '1'"

**Step 3: Add os import and set FORCE_COLOR in _render_statusline()**

In `__init__.py`, add import at top:

```python
import os
```

Then modify `_render_statusline()`:

```python
def _render_statusline() -> None:
    """Read from stdin and render statusline."""
    config = load_config()

    # Enable colors for termcolor (stdout is not a TTY in Claude Code hooks)
    if config.colors:
        os.environ["FORCE_COLOR"] = "1"

    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    ctx = RenderContext(debug=config.debug, data=data, cache_dir=config.cache_dir)
    modules = load_modules(config, ctx)

    for mod in modules:
        try:
            output = mod.render()
            if output:
                print(output)
        except Exception as e:
            if config.debug:
                print(colored(f"[!] {mod.name}: {e}", "red"))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_main.py::test_render_statusline_sets_force_color -v`
Expected: PASS

**Step 5: Commit**

```bash
uv run ruff format packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
uv run ruff check --fix packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
uv run ty check
git add packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
git commit -m "feat(statuskit): set FORCE_COLOR when colors config enabled"
```

---

## Task 4: Test colors=false disables FORCE_COLOR

**Files:**
- Test: `packages/statuskit/tests/test_main.py`

**Step 1: Write the test for colors=false**

Add to `test_main.py`:

```python
def test_render_statusline_respects_colors_false(monkeypatch):
    """_render_statusline does not set FORCE_COLOR when colors=false."""
    import os
    from statuskit import _render_statusline
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Remove FORCE_COLOR if present
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {"model": {"display_name": "Test"}}
    mock_config = Config(modules=["model"], colors=False)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        _render_statusline()

    assert os.environ.get("FORCE_COLOR") is None
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_main.py::test_render_statusline_respects_colors_false -v`
Expected: PASS (implementation already handles this case)

**Step 3: Commit**

```bash
uv run ruff format packages/statuskit/tests/test_main.py
uv run ruff check --fix packages/statuskit/tests/test_main.py
uv run ty check
git add packages/statuskit/tests/test_main.py
git commit -m "test(statuskit): verify colors=false disables FORCE_COLOR"
```

---

## Task 5: Integration test - verify ANSI codes in output

**Files:**
- Test: `packages/statuskit/tests/test_main.py`

**Step 1: Write integration test for ANSI output**

Add to `test_main.py`:

```python
def test_main_outputs_ansi_codes_when_colors_enabled(capsys, monkeypatch):
    """main outputs ANSI escape codes when colors=true."""
    from statuskit.core.config import Config

    monkeypatch.setattr(sys, "argv", ["statuskit"])

    # Ensure FORCE_COLOR is not pre-set
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    input_data = {
        "model": {"display_name": "Opus"},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {"input_tokens": 1000},
        },
    }
    mock_config = Config(modules=["model"], colors=True)

    with (
        patch("sys.stdin", mock_stdin),
        patch("json.load", return_value=input_data),
        patch("statuskit.load_config", return_value=mock_config),
    ):
        main()

    captured = capsys.readouterr()
    # ANSI escape sequence starts with \x1b[
    assert "\x1b[" in captured.out, f"Expected ANSI codes in output, got: {repr(captured.out)}"
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest packages/statuskit/tests/test_main.py::test_main_outputs_ansi_codes_when_colors_enabled -v`
Expected: PASS

**Step 3: Commit**

```bash
uv run ruff format packages/statuskit/tests/test_main.py
uv run ruff check --fix packages/statuskit/tests/test_main.py
uv run ty check
git add packages/statuskit/tests/test_main.py
git commit -m "test(statuskit): integration test for ANSI color output"
```

---

## Task 6: Run full test suite and manual verification

**Step 1: Run full test suite**

Run: `uv run pytest packages/statuskit/tests/ -v`
Expected: All tests PASS

**Step 2: Manual verification**

Run:
```bash
echo '{"model":{"display_name":"Test"}}' | uv run statuskit 2>/dev/null | xxd | head -5
```
Expected: Output contains `1b5b` (ANSI escape sequence `\x1b[`)

**Step 3: Final commit (if any cleanup needed)**

No commit needed if all tests pass.

---

## Summary

| Task | Description | Files Modified |
|------|-------------|----------------|
| 1 | Add `colors` field to Config | config.py, test_config.py |
| 2 | Parse `colors` from TOML | config.py, test_config.py |
| 3 | Set FORCE_COLOR env var | __init__.py, test_main.py |
| 4 | Test colors=false behavior | test_main.py |
| 5 | Integration test for ANSI output | test_main.py |
| 6 | Full test suite verification | - |
