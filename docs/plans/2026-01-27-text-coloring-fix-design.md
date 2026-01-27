# Fix: Text Coloring in Statusline

**Task:** claude-tools-5dl.4
**Date:** 2026-01-27

## Problem

Statuskit uses `termcolor` for ANSI color output. When Claude Code calls statuskit via its statusline hook, stdout is not a TTY (`sys.stdout.isatty()` returns `False`). Termcolor automatically disables colors in non-TTY environments.

## Solution

Set `FORCE_COLOR=1` environment variable before termcolor calls. Add config option to control this behavior.

## Changes

### 1. `core/config.py`

Add `colors` field to Config dataclass:

```python
@dataclass
class Config:
    debug: bool = False
    colors: bool = True  # Enable ANSI colors (default: on)
    modules: list[str] = ...
```

Parse in `load_config()`:

```python
return Config(
    debug=data.get("debug", False),
    colors=data.get("colors", True),
    ...
)
```

### 2. `__init__.py`

Add import and set environment variable in `_render_statusline()`:

```python
import os

def _render_statusline() -> None:
    config = load_config()

    # Enable colors for termcolor (stdout is not a TTY in Claude Code hooks)
    if config.colors:
        os.environ["FORCE_COLOR"] = "1"

    ...
```

## Config Example

```toml
colors = false  # Disable colors if needed
```

## Testing

```bash
echo '{"model":{"display_name":"Test"}}' | uv run statuskit | xxd | head -5
# Should contain ANSI codes (\x1b[...)
```
