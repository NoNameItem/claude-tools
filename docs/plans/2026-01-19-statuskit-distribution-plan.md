# Statuskit Distribution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add CLI interface with --help, --version, and `setup` command for automated Claude Code integration.

**Architecture:** argparse-based CLI with subcommands. `setup` command manages settings.json hooks and statuskit.toml configs across three scopes (user/project/local). Config loading upgraded to support scope hierarchy.

**Tech Stack:** Python 3.11+, argparse, tomllib, json, pathlib

---

## Task 1: Update pyproject.toml with full metadata

**Files:**
- Modify: `packages/statuskit/pyproject.toml`

**Step 1: Update pyproject.toml with complete metadata**

```toml
[project]
name = "statuskit"
version = "0.1.0"
description = "Modular statusline for Claude Code"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Artem Vasin", email = "nonameitem@me.com" }]
keywords = ["claude", "claude-code", "statusline", "cli"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
]
dependencies = ["termcolor"]

[project.scripts]
statuskit = "statuskit:main"

[project.urls]
Homepage = "https://github.com/NoNameItem/claude-tools/tree/master/packages/statuskit"
Repository = "https://github.com/NoNameItem/claude-tools"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/statuskit"]
```

**Step 2: Verify build works**

Run: `cd packages/statuskit && uv build`
Expected: Successfully builds wheel in dist/

**Step 3: Commit**

```bash
git add packages/statuskit/pyproject.toml
git commit -m "chore(statuskit): add full PyPI metadata to pyproject.toml"
```

---

## Task 2: Create README.md for PyPI

**Files:**
- Create: `packages/statuskit/README.md`

**Step 1: Create README.md**

```markdown
# statuskit

Modular statusline for Claude Code.

## Installation

```bash
uv tool install statuskit
# or
pipx install statuskit
```

## Quick Start

```bash
statuskit setup
```

This adds the statusline hook to your Claude Code settings.

## Configuration

Configuration file locations (in priority order):
1. `.claude/statuskit.local.toml` (local, gitignored)
2. `.claude/statuskit.toml` (project)
3. `~/.claude/statuskit.toml` (user)

Example configuration:

```toml
# Modules to display (in order)
modules = ["model", "git", "beads", "quota"]

# Enable debug output
# debug = false
```

## Built-in Modules

- **model** — Display current Claude model name
- **git** — Show git branch and status
- **beads** — Display active beads tasks
- **quota** — Track token usage

## License

MIT
```

**Step 2: Verify README included in build**

Run: `cd packages/statuskit && uv build && unzip -l dist/*.whl | grep -i readme`
Expected: Shows README.md in wheel metadata

**Step 3: Commit**

```bash
git add packages/statuskit/README.md
git commit -m "docs(statuskit): add README for PyPI"
```

---

## Task 3: Add CLI argument parsing with --help and --version

**Files:**
- Create: `packages/statuskit/src/statuskit/cli.py`
- Modify: `packages/statuskit/src/statuskit/__init__.py`
- Create: `packages/statuskit/tests/test_cli.py`

**Step 1: Write failing test for --version**

```python
# packages/statuskit/tests/test_cli.py
"""Tests for CLI argument parsing."""

import pytest

from statuskit.cli import create_parser, get_version


def test_version_returns_string():
    """--version returns version string."""
    version = get_version()
    assert isinstance(version, str)
    assert version  # not empty


def test_parser_version_action(capsys):
    """--version prints version and exits."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "statuskit" in captured.out.lower() or get_version() in captured.out
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_cli.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# packages/statuskit/src/statuskit/cli.py
"""CLI argument parsing for statuskit."""

import argparse
from importlib.metadata import version


def get_version() -> str:
    """Get statuskit version from package metadata."""
    try:
        return version("statuskit")
    except Exception:
        return "0.1.0"  # fallback for development


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for statuskit CLI."""
    parser = argparse.ArgumentParser(
        prog="statuskit",
        description="Modular statusline for Claude Code",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"statuskit {get_version()}",
    )
    return parser
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/cli.py packages/statuskit/tests/test_cli.py
git commit -m "feat(statuskit): add CLI parser with --version"
```

---

## Task 4: Add --help with module list

**Files:**
- Modify: `packages/statuskit/src/statuskit/cli.py`
- Modify: `packages/statuskit/tests/test_cli.py`

**Step 1: Write failing test for --help content**

```python
# Add to packages/statuskit/tests/test_cli.py

def test_help_shows_modules(capsys):
    """--help shows built-in modules list."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    # Check modules are listed
    assert "model" in captured.out
    assert "git" in captured.out
    assert "beads" in captured.out
    assert "quota" in captured.out
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_cli.py::test_help_shows_modules -v`
Expected: FAIL (modules not in help)

**Step 3: Update parser with epilog**

```python
# Update create_parser in packages/statuskit/src/statuskit/cli.py

MODULES_HELP = """
Built-in modules:
  model                  Display current Claude model name
  git                    Show git branch and status
  beads                  Display active beads tasks
  quota                  Track token usage
"""


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for statuskit CLI."""
    parser = argparse.ArgumentParser(
        prog="statuskit",
        description="Modular statusline for Claude Code",
        epilog=MODULES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"statuskit {get_version()}",
    )
    return parser
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_cli.py::test_help_shows_modules -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/cli.py packages/statuskit/tests/test_cli.py
git commit -m "feat(statuskit): add modules list to --help output"
```

---

## Task 5: Wire CLI parser into main()

**Files:**
- Modify: `packages/statuskit/src/statuskit/__init__.py`
- Modify: `packages/statuskit/tests/test_main.py`

**Step 1: Write failing test for CLI integration**

```python
# Add to packages/statuskit/tests/test_main.py

def test_main_with_version_flag(capsys, monkeypatch):
    """main() handles --version flag."""
    import sys
    monkeypatch.setattr(sys, "argv", ["statuskit", "--version"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "statuskit" in captured.out.lower() or "0.1.0" in captured.out
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_main.py::test_main_with_version_flag -v`
Expected: FAIL (current main ignores argv)

**Step 3: Update main() to use CLI parser**

```python
# packages/statuskit/src/statuskit/__init__.py
"""Modular statusline kit for Claude Code."""

import json
import sys

from termcolor import colored

from .cli import create_parser
from .core.config import load_config
from .core.loader import load_modules
from .core.models import RenderContext, StatusInput


def main() -> None:
    """Entry point for statuskit command."""
    # Parse CLI arguments first
    parser = create_parser()
    parser.parse_args()  # handles --version, --help, exits if needed

    # Main mode: read from stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        return

    # Load config
    config = load_config()

    # Read data from Claude Code
    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    # Create context
    ctx = RenderContext(debug=config.debug, data=data)

    # Load modules
    modules = load_modules(config, ctx)

    # Render modules
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

Run: `cd packages/statuskit && uv run pytest tests/test_main.py::test_main_with_version_flag -v`
Expected: PASS

**Step 5: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
git commit -m "feat(statuskit): wire CLI parser into main entry point"
```

---

## Task 6: Add Scope enum and path resolution

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/__init__.py`
- Create: `packages/statuskit/src/statuskit/setup/paths.py`
- Create: `packages/statuskit/tests/test_setup_paths.py`

**Step 1: Write failing tests for Scope and paths**

```python
# packages/statuskit/tests/test_setup_paths.py
"""Tests for setup path resolution."""

from pathlib import Path

import pytest

from statuskit.setup.paths import Scope, get_config_path, get_settings_path


class TestScope:
    """Tests for Scope enum."""

    def test_scope_values(self):
        """Scope has user, project, local values."""
        assert Scope.USER.value == "user"
        assert Scope.PROJECT.value == "project"
        assert Scope.LOCAL.value == "local"

    def test_scope_from_string(self):
        """Scope can be created from string."""
        assert Scope("user") == Scope.USER
        assert Scope("project") == Scope.PROJECT
        assert Scope("local") == Scope.LOCAL


class TestGetSettingsPath:
    """Tests for get_settings_path function."""

    def test_user_scope(self):
        """User scope returns ~/.claude/settings.json."""
        path = get_settings_path(Scope.USER)
        assert path == Path.home() / ".claude" / "settings.json"

    def test_project_scope(self):
        """Project scope returns .claude/settings.json."""
        path = get_settings_path(Scope.PROJECT)
        assert path == Path(".claude") / "settings.json"

    def test_local_scope(self):
        """Local scope returns .claude/settings.local.json."""
        path = get_settings_path(Scope.LOCAL)
        assert path == Path(".claude") / "settings.local.json"


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_user_scope(self):
        """User scope returns ~/.claude/statuskit.toml."""
        path = get_config_path(Scope.USER)
        assert path == Path.home() / ".claude" / "statuskit.toml"

    def test_project_scope(self):
        """Project scope returns .claude/statuskit.toml."""
        path = get_config_path(Scope.PROJECT)
        assert path == Path(".claude") / "statuskit.toml"

    def test_local_scope(self):
        """Local scope returns .claude/statuskit.local.toml."""
        path = get_config_path(Scope.LOCAL)
        assert path == Path(".claude") / "statuskit.local.toml"
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_paths.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create paths module**

```python
# packages/statuskit/src/statuskit/setup/__init__.py
"""Setup command for statuskit."""
```

```python
# packages/statuskit/src/statuskit/setup/paths.py
"""Path resolution for setup command."""

from enum import Enum
from pathlib import Path


class Scope(Enum):
    """Installation scope for statuskit."""

    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


def get_settings_path(scope: Scope) -> Path:
    """Get settings.json path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / ".claude" / "settings.json"
    elif scope == Scope.PROJECT:
        return Path(".claude") / "settings.json"
    else:  # LOCAL
        return Path(".claude") / "settings.local.json"


def get_config_path(scope: Scope) -> Path:
    """Get statuskit.toml path for the given scope."""
    if scope == Scope.USER:
        return Path.home() / ".claude" / "statuskit.toml"
    elif scope == Scope.PROJECT:
        return Path(".claude") / "statuskit.toml"
    else:  # LOCAL
        return Path(".claude") / "statuskit.local.toml"
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_paths.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup packages/statuskit/tests/test_setup_paths.py
git commit -m "feat(statuskit): add Scope enum and path resolution"
```

---

## Task 7: Add is_our_hook detection

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/hooks.py`
- Create: `packages/statuskit/tests/test_setup_hooks.py`

**Step 1: Write failing tests for hook detection**

```python
# packages/statuskit/tests/test_setup_hooks.py
"""Tests for hook detection."""

import pytest

from statuskit.setup.hooks import is_our_hook


class TestIsOurHook:
    """Tests for is_our_hook function."""

    def test_simple_statuskit(self):
        """Detects simple 'statuskit' command."""
        assert is_our_hook({"command": "statuskit"}) is True

    def test_statuskit_with_path(self):
        """Detects statuskit with full path."""
        assert is_our_hook({"command": "/usr/local/bin/statuskit"}) is True
        assert is_our_hook({"command": "~/.local/bin/statuskit"}) is True

    def test_statuskit_with_flags(self):
        """Detects statuskit with flags."""
        assert is_our_hook({"command": "statuskit --debug"}) is True

    def test_other_command(self):
        """Rejects other commands."""
        assert is_our_hook({"command": "other-script.sh"}) is False
        assert is_our_hook({"command": "/path/to/other"}) is False

    def test_empty_command(self):
        """Handles empty command."""
        assert is_our_hook({"command": ""}) is False
        assert is_our_hook({}) is False

    def test_malformed_command(self):
        """Handles malformed command strings."""
        assert is_our_hook({"command": "statuskit 'unclosed"}) is False

    def test_type_mismatch(self):
        """Only checks command type hooks."""
        assert is_our_hook({"type": "shell", "command": "statuskit"}) is True
        assert is_our_hook({"command": "statuskit"}) is True
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create hooks module**

```python
# packages/statuskit/src/statuskit/setup/hooks.py
"""Hook detection for setup command."""

import shlex
from pathlib import Path


def is_our_hook(hook: dict) -> bool:
    """Check if the hook points to statuskit.

    Recognizes:
    - statuskit
    - /usr/local/bin/statuskit
    - ~/.local/bin/statuskit --debug
    """
    cmd = hook.get("command", "")
    if not cmd:
        return False
    try:
        first_word = shlex.split(cmd)[0]
        return Path(first_word).name == "statuskit"
    except ValueError:
        return False
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/hooks.py packages/statuskit/tests/test_setup_hooks.py
git commit -m "feat(statuskit): add is_our_hook detection"
```

---

## Task 8: Add settings.json read/write utilities

**Files:**
- Modify: `packages/statuskit/src/statuskit/setup/hooks.py`
- Modify: `packages/statuskit/tests/test_setup_hooks.py`

**Step 1: Write failing tests for settings read/write**

```python
# Add to packages/statuskit/tests/test_setup_hooks.py

import json
from pathlib import Path


class TestReadSettings:
    """Tests for read_settings function."""

    def test_read_existing_settings(self, tmp_path):
        """Reads existing settings.json."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"foo": "bar"}')

        data = read_settings(settings_path)
        assert data == {"foo": "bar"}

    def test_read_nonexistent_returns_empty(self, tmp_path):
        """Returns empty dict for nonexistent file."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"

        data = read_settings(settings_path)
        assert data == {}

    def test_read_invalid_json_raises(self, tmp_path):
        """Raises ValueError for invalid JSON."""
        from statuskit.setup.hooks import read_settings

        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            read_settings(settings_path)


class TestWriteSettings:
    """Tests for write_settings function."""

    def test_write_creates_file(self, tmp_path):
        """Creates settings.json with data."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data == {"foo": "bar"}

    def test_write_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / ".claude" / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        assert settings_path.exists()

    def test_write_preserves_formatting(self, tmp_path):
        """Writes with indent for readability."""
        from statuskit.setup.hooks import write_settings

        settings_path = tmp_path / "settings.json"
        write_settings(settings_path, {"foo": "bar"})

        content = settings_path.read_text()
        assert "\n" in content  # has newlines (indented)
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py::TestReadSettings -v`
Expected: FAIL with ImportError

**Step 3: Add read/write functions**

```python
# Add to packages/statuskit/src/statuskit/setup/hooks.py

import json
# ... existing imports ...


def read_settings(path: Path) -> dict:
    """Read settings.json file.

    Returns empty dict if file doesn't exist.
    Raises ValueError if file contains invalid JSON.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e


def write_settings(path: Path, data: dict) -> None:
    """Write settings.json file.

    Creates parent directories if needed.
    Uses 2-space indent for readability.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/hooks.py packages/statuskit/tests/test_setup_hooks.py
git commit -m "feat(statuskit): add settings.json read/write utilities"
```

---

## Task 9: Add backup creation utility

**Files:**
- Modify: `packages/statuskit/src/statuskit/setup/hooks.py`
- Modify: `packages/statuskit/tests/test_setup_hooks.py`

**Step 1: Write failing tests for backup**

```python
# Add to packages/statuskit/tests/test_setup_hooks.py

class TestCreateBackup:
    """Tests for create_backup function."""

    def test_creates_bak_file(self, tmp_path):
        """Creates .bak file next to original."""
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"original": true}')

        create_backup(original)

        backup = tmp_path / "settings.json.bak"
        assert backup.exists()
        assert backup.read_text() == '{"original": true}'

    def test_overwrites_existing_backup(self, tmp_path):
        """Overwrites existing .bak file."""
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"new": true}')

        backup = tmp_path / "settings.json.bak"
        backup.write_text('{"old": true}')

        create_backup(original)

        assert backup.read_text() == '{"new": true}'

    def test_returns_backup_path(self, tmp_path):
        """Returns path to backup file."""
        from statuskit.setup.hooks import create_backup

        original = tmp_path / "settings.json"
        original.write_text('{"data": true}')

        result = create_backup(original)

        assert result == tmp_path / "settings.json.bak"
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py::TestCreateBackup -v`
Expected: FAIL with ImportError

**Step 3: Add backup function**

```python
# Add to packages/statuskit/src/statuskit/setup/hooks.py

import shutil
# ... existing code ...


def create_backup(path: Path) -> Path:
    """Create backup of file as .bak.

    Overwrites existing .bak file.
    Returns path to backup file.
    """
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_hooks.py::TestCreateBackup -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/hooks.py packages/statuskit/tests/test_setup_hooks.py
git commit -m "feat(statuskit): add backup creation utility"
```

---

## Task 10: Add config file creation utility

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/config.py`
- Create: `packages/statuskit/tests/test_setup_config.py`

**Step 1: Write failing tests for config creation**

```python
# packages/statuskit/tests/test_setup_config.py
"""Tests for config file creation."""

from pathlib import Path

import pytest


class TestCreateConfig:
    """Tests for create_config function."""

    def test_creates_default_config(self, tmp_path):
        """Creates statuskit.toml with defaults."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()
        content = config_path.read_text()
        assert 'modules = ["model", "git", "beads", "quota"]' in content

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / ".claude" / "statuskit.toml"
        create_config(config_path)

        assert config_path.exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        """Does not overwrite existing config."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("custom = true")

        create_config(config_path)

        assert config_path.read_text() == "custom = true"

    def test_returns_created_true(self, tmp_path):
        """Returns True when config was created."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        result = create_config(config_path)

        assert result is True

    def test_returns_created_false_if_exists(self, tmp_path):
        """Returns False when config already existed."""
        from statuskit.setup.config import create_config

        config_path = tmp_path / "statuskit.toml"
        config_path.write_text("existing = true")

        result = create_config(config_path)

        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_config.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create config module**

```python
# packages/statuskit/src/statuskit/setup/config.py
"""Config file creation for setup command."""

from pathlib import Path

DEFAULT_CONFIG = '''\
# Statuskit configuration
# See: https://github.com/NoNameItem/claude-tools

# Modules to display (in order)
modules = ["model", "git", "beads", "quota"]

# Enable debug output
# debug = false
'''


def create_config(path: Path) -> bool:
    """Create statuskit.toml with default content.

    Does not overwrite existing file.
    Returns True if file was created, False if it already existed.
    """
    if path.exists():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG)
    return True
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/config.py packages/statuskit/tests/test_setup_config.py
git commit -m "feat(statuskit): add config file creation utility"
```

---

## Task 11: Add setup --check command

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/commands.py`
- Create: `packages/statuskit/tests/test_setup_commands.py`
- Modify: `packages/statuskit/src/statuskit/cli.py`

**Step 1: Write failing tests for --check**

```python
# packages/statuskit/tests/test_setup_commands.py
"""Tests for setup commands."""

from pathlib import Path

import pytest


class TestCheckInstallation:
    """Tests for check_installation function."""

    def test_no_installation(self, tmp_path, monkeypatch):
        """Shows not installed for all scopes."""
        from statuskit.setup.commands import check_installation

        # Mock home to tmp_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(tmp_path / "project")
        (tmp_path / "project").mkdir(parents=True)

        result = check_installation()

        assert "User:" in result and "Not installed" in result
        assert "Project:" in result and "Not installed" in result
        assert "Local:" in result and "Not installed" in result

    def test_user_installed(self, tmp_path, monkeypatch):
        """Shows installed for user scope."""
        from statuskit.setup.commands import check_installation
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}})
        )

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(tmp_path / "project")
        (tmp_path / "project").mkdir(parents=True)

        result = check_installation()

        assert "User:" in result and "Installed" in result

    def test_project_installed(self, tmp_path, monkeypatch):
        """Shows installed for project scope."""
        from statuskit.setup.commands import check_installation
        import json

        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}})
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(project)

        result = check_installation()

        assert "Project:" in result and "Installed" in result
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestCheckInstallation -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create commands module with check_installation**

```python
# packages/statuskit/src/statuskit/setup/commands.py
"""Setup command implementations."""

from .hooks import is_our_hook, read_settings
from .paths import Scope, get_settings_path


def check_installation() -> str:
    """Check installation status for all scopes.

    Returns formatted string showing status for each scope.
    """
    lines = []
    for scope in Scope:
        settings_path = get_settings_path(scope)
        settings = read_settings(settings_path)
        hook = settings.get("statusLine", {})

        if is_our_hook(hook):
            status = "\u2713 Installed"
        else:
            status = "\u2717 Not installed"

        # Capitalize scope name
        scope_name = scope.value.capitalize()
        lines.append(f"{scope_name}:    {status}")

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestCheckInstallation -v`
Expected: PASS

**Step 5: Add --check to CLI parser**

```python
# Update packages/statuskit/src/statuskit/cli.py to add setup subcommand

def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for statuskit CLI."""
    parser = argparse.ArgumentParser(
        prog="statuskit",
        description="Modular statusline for Claude Code",
        epilog=MODULES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"statuskit {get_version()}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # setup subcommand
    setup_parser = subparsers.add_parser(
        "setup",
        help="Configure Claude Code integration",
    )
    setup_parser.add_argument(
        "-s", "--scope",
        choices=["user", "project", "local"],
        default="user",
        help="Installation scope (default: user)",
    )
    setup_parser.add_argument(
        "--check",
        action="store_true",
        help="Check installation status (all scopes)",
    )
    setup_parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove integration (requires --scope)",
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmations, backup and overwrite",
    )

    return parser
```

**Step 6: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/commands.py packages/statuskit/tests/test_setup_commands.py packages/statuskit/src/statuskit/cli.py
git commit -m "feat(statuskit): add setup --check command"
```

---

## Task 12: Add setup install command (core logic)

**Files:**
- Modify: `packages/statuskit/src/statuskit/setup/commands.py`
- Modify: `packages/statuskit/tests/test_setup_commands.py`

**Step 1: Write failing tests for install_hook**

```python
# Add to packages/statuskit/tests/test_setup_commands.py

class TestInstallHook:
    """Tests for install_hook function."""

    def test_installs_to_user_scope(self, tmp_path, monkeypatch):
        """Installs hook to user scope."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        assert settings["statusLine"]["command"] == "statuskit"

    def test_creates_config_file(self, tmp_path, monkeypatch):
        """Creates statuskit.toml alongside hook."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        install_hook(Scope.USER, force=False, ui=None)

        config_path = home / ".claude" / "statuskit.toml"
        assert config_path.exists()

    def test_already_installed_returns_early(self, tmp_path, monkeypatch):
        """Returns early if already installed."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}})
        )

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.already_installed is True

    def test_foreign_hook_with_force_creates_backup(self, tmp_path, monkeypatch):
        """Creates backup when overwriting foreign hook with --force."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "other-script"}})
        )

        monkeypatch.setattr(Path, "home", lambda: home)

        result = install_hook(Scope.USER, force=True, ui=None)

        assert result.success is True
        assert result.backup_created is True
        assert (home / ".claude" / "settings.json.bak").exists()
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHook -v`
Expected: FAIL with ImportError

**Step 3: Add InstallResult and install_hook**

```python
# Update packages/statuskit/src/statuskit/setup/commands.py

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import create_config
from .hooks import create_backup, is_our_hook, read_settings, write_settings
from .paths import Scope, get_config_path, get_settings_path


class UI(Protocol):
    """Protocol for user interaction."""

    def confirm(self, message: str) -> bool:
        """Ask user for yes/no confirmation."""
        ...

    def choose(self, message: str, options: list[str]) -> int:
        """Ask user to choose from options. Returns 0-based index."""
        ...


@dataclass
class InstallResult:
    """Result of install_hook operation."""

    success: bool = False
    already_installed: bool = False
    backup_created: bool = False
    config_created: bool = False
    message: str = ""


def install_hook(scope: Scope, force: bool, ui: UI | None) -> InstallResult:
    """Install statuskit hook to settings.json.

    Args:
        scope: Installation scope (user/project/local)
        force: Skip confirmations, create backup
        ui: User interaction handler (None for non-interactive)

    Returns:
        InstallResult with operation details
    """
    settings_path = get_settings_path(scope)
    config_path = get_config_path(scope)

    # Read current settings
    try:
        settings = read_settings(settings_path)
    except ValueError as e:
        return InstallResult(success=False, message=str(e))

    current_hook = settings.get("statusLine", {})

    # Check if already installed
    if is_our_hook(current_hook):
        # Still create config if missing
        config_created = create_config(config_path)
        return InstallResult(
            success=True,
            already_installed=True,
            config_created=config_created,
            message="Already installed",
        )

    # Handle foreign hook
    backup_created = False
    if current_hook.get("command"):
        if force:
            create_backup(settings_path)
            backup_created = True
        elif ui:
            foreign_cmd = current_hook.get("command", "")
            if not ui.confirm(
                f"statusLine points to: {foreign_cmd}\n"
                "Overwrite? (backup will be created)"
            ):
                return InstallResult(success=False, message="Cancelled by user")
            create_backup(settings_path)
            backup_created = True
        else:
            return InstallResult(
                success=False,
                message=f"Foreign hook exists: {current_hook.get('command')}. Use --force to overwrite.",
            )

    # Install hook
    settings["statusLine"] = {"type": "command", "command": "statuskit"}
    write_settings(settings_path, settings)

    # Create config
    config_created = create_config(config_path)

    return InstallResult(
        success=True,
        backup_created=backup_created,
        config_created=config_created,
        message="Installed successfully",
    )


def check_installation() -> str:
    """Check installation status for all scopes."""
    lines = []
    for scope in Scope:
        settings_path = get_settings_path(scope)
        settings = read_settings(settings_path)
        hook = settings.get("statusLine", {})

        if is_our_hook(hook):
            status = "\u2713 Installed"
        else:
            status = "\u2717 Not installed"

        scope_name = scope.value.capitalize()
        lines.append(f"{scope_name}:    {status}")

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHook -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/commands.py packages/statuskit/tests/test_setup_commands.py
git commit -m "feat(statuskit): add install_hook core logic"
```

---

## Task 13: Add gitignore handling for local scope

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/gitignore.py`
- Create: `packages/statuskit/tests/test_setup_gitignore.py`
- Modify: `packages/statuskit/src/statuskit/setup/commands.py`

**Step 1: Write failing tests for gitignore utilities**

```python
# packages/statuskit/tests/test_setup_gitignore.py
"""Tests for gitignore handling."""

import subprocess
from pathlib import Path

import pytest


class TestIsInGitRepo:
    """Tests for is_in_git_repo function."""

    def test_returns_true_in_git_repo(self, tmp_path, monkeypatch):
        """Returns True when in a git repository."""
        from statuskit.setup.gitignore import is_in_git_repo

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        monkeypatch.chdir(tmp_path)

        assert is_in_git_repo() is True

    def test_returns_false_outside_git_repo(self, tmp_path, monkeypatch):
        """Returns False when not in a git repository."""
        from statuskit.setup.gitignore import is_in_git_repo

        monkeypatch.chdir(tmp_path)

        assert is_in_git_repo() is False


class TestIsFileIgnored:
    """Tests for is_file_ignored function."""

    def test_ignored_file_returns_true(self, tmp_path, monkeypatch):
        """Returns True for ignored file."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / ".gitignore").write_text("*.local.*\n")
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.local.json") is True

    def test_not_ignored_file_returns_false(self, tmp_path, monkeypatch):
        """Returns False for non-ignored file."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.json") is False

    def test_covered_by_directory_pattern(self, tmp_path, monkeypatch):
        """Returns True when covered by directory pattern."""
        from statuskit.setup.gitignore import is_file_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / ".gitignore").write_text(".claude/\n")
        monkeypatch.chdir(tmp_path)

        assert is_file_ignored(".claude/settings.local.json") is True


class TestEnsureLocalFilesIgnored:
    """Tests for ensure_local_files_ignored function."""

    def test_adds_pattern_when_not_ignored(self, tmp_path, monkeypatch):
        """Adds pattern to .gitignore when files not ignored."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is True
        assert ".claude/*.local.*" in (tmp_path / ".gitignore").read_text()

    def test_creates_gitignore_if_missing(self, tmp_path, monkeypatch):
        """Creates .gitignore if it doesn't exist."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is True
        assert (tmp_path / ".gitignore").exists()

    def test_returns_false_when_already_ignored(self, tmp_path, monkeypatch):
        """Returns False when files already ignored."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / ".gitignore").write_text(".claude/*.local.*\n")
        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is False

    def test_returns_false_when_not_in_git_repo(self, tmp_path, monkeypatch):
        """Returns False when not in git repository."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        monkeypatch.chdir(tmp_path)

        result = ensure_local_files_ignored()

        assert result is False
        assert not (tmp_path / ".gitignore").exists()

    def test_preserves_existing_content(self, tmp_path, monkeypatch):
        """Preserves existing .gitignore content."""
        from statuskit.setup.gitignore import ensure_local_files_ignored

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
        monkeypatch.chdir(tmp_path)

        ensure_local_files_ignored()

        content = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in content
        assert ".env" in content
        assert ".claude/*.local.*" in content
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_gitignore.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create gitignore module**

```python
# packages/statuskit/src/statuskit/setup/gitignore.py
"""Gitignore handling for local scope setup."""

import subprocess
from pathlib import Path

LOCAL_FILES = [
    ".claude/settings.local.json",
    ".claude/statuskit.local.toml",
]

GITIGNORE_PATTERN = ".claude/*.local.*"


def is_in_git_repo() -> bool:
    """Check if current directory is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
    )
    return result.returncode == 0


def is_file_ignored(path: str) -> bool:
    """Check if a file would be ignored by git.

    Uses `git check-ignore` to check against all gitignore rules.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        capture_output=True,
    )
    return result.returncode == 0


def ensure_local_files_ignored() -> bool:
    """Ensure local scope files are in .gitignore.

    Returns True if pattern was added, False if already ignored or not in git repo.
    """
    if not is_in_git_repo():
        return False

    # Check if files are already ignored
    all_ignored = all(is_file_ignored(f) for f in LOCAL_FILES)
    if all_ignored:
        return False

    # Add pattern to .gitignore
    gitignore_path = Path(".gitignore")

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = ""

    content += f"{GITIGNORE_PATTERN}\n"
    gitignore_path.write_text(content)

    return True
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_gitignore.py -v`
Expected: PASS

**Step 5: Write failing test for install_hook gitignore integration**

```python
# Add to packages/statuskit/tests/test_setup_commands.py

class TestInstallHookGitignore:
    """Tests for install_hook gitignore handling."""

    def test_adds_gitignore_for_local_scope(self, tmp_path, monkeypatch):
        """Adds gitignore pattern when installing to local scope."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import subprocess

        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        monkeypatch.chdir(project)

        result = install_hook(Scope.LOCAL, force=False, ui=None)

        assert result.success is True
        assert result.gitignore_updated is True
        assert ".claude/*.local.*" in (project / ".gitignore").read_text()

    def test_no_gitignore_for_user_scope(self, tmp_path, monkeypatch):
        """Does not modify gitignore for user scope."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import subprocess

        home = tmp_path / "home"
        project = tmp_path / "project"
        (home / ".claude").mkdir(parents=True)
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, capture_output=True)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        result = install_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        assert result.gitignore_updated is False
```

**Step 6: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHookGitignore -v`
Expected: FAIL (gitignore_updated not in InstallResult)

**Step 7: Update InstallResult and install_hook**

```python
# Update in packages/statuskit/src/statuskit/setup/commands.py

from .gitignore import ensure_local_files_ignored

@dataclass
class InstallResult:
    """Result of install_hook operation."""

    success: bool = False
    already_installed: bool = False
    backup_created: bool = False
    config_created: bool = False
    gitignore_updated: bool = False  # NEW
    higher_scope_installed: bool = False
    higher_scope: Scope | None = None
    message: str = ""


def install_hook(scope: Scope, force: bool, ui: UI | None) -> InstallResult:
    """Install statuskit hook to settings.json."""
    settings_path = get_settings_path(scope)
    config_path = get_config_path(scope)

    # ... existing higher scope check code ...

    # ... existing hook installation code ...

    # Handle gitignore for local scope
    gitignore_updated = False
    if scope == Scope.LOCAL:
        gitignore_updated = ensure_local_files_ignored()

    # Create config
    config_created = create_config(config_path)

    return InstallResult(
        success=True,
        backup_created=backup_created,
        config_created=config_created,
        gitignore_updated=gitignore_updated,
        message="Installed successfully",
    )
```

**Step 8: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHookGitignore -v`
Expected: PASS

**Step 9: Update main() to show gitignore message**

```python
# Update the install section in main() to show gitignore message

        elif result.success:
            print(f"\u2713 Added statusline hook to {scope.value} scope.")
            if result.backup_created:
                print(f"\u2713 Created backup of previous settings.")
            if result.config_created:
                print(f"\u2713 Created config file.")
            if result.gitignore_updated:
                print(f"\u2713 Added .claude/*.local.* to .gitignore")
            print("\nRun `claude` to see your new statusline!")
```

**Step 10: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 11: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/gitignore.py packages/statuskit/tests/test_setup_gitignore.py packages/statuskit/src/statuskit/setup/commands.py packages/statuskit/tests/test_setup_commands.py packages/statuskit/src/statuskit/__init__.py
git commit -m "feat(statuskit): add gitignore handling for local scope"
```

---

## Task 14: Add setup --remove command

**Files:**
- Modify: `packages/statuskit/src/statuskit/setup/commands.py`
- Modify: `packages/statuskit/tests/test_setup_commands.py`

**Step 1: Write failing tests for remove_hook**

```python
# Add to packages/statuskit/tests/test_setup_commands.py

class TestRemoveHook:
    """Tests for remove_hook function."""

    def test_removes_our_hook(self, tmp_path, monkeypatch):
        """Removes statuskit hook from settings."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}, "other": "setting"})
        )

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.success is True
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        assert "statusLine" not in settings
        assert settings["other"] == "setting"

    def test_not_installed_returns_early(self, tmp_path, monkeypatch):
        """Returns early if not installed."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.not_installed is True

    def test_foreign_hook_requires_confirmation(self, tmp_path, monkeypatch):
        """Foreign hook requires confirmation or --force."""
        from statuskit.setup.commands import remove_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "other-script"}})
        )

        monkeypatch.setattr(Path, "home", lambda: home)

        result = remove_hook(Scope.USER, force=False, ui=None)

        assert result.success is False
        assert "other-script" in result.message
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestRemoveHook -v`
Expected: FAIL with ImportError

**Step 3: Add RemoveResult and remove_hook**

```python
# Add to packages/statuskit/src/statuskit/setup/commands.py

@dataclass
class RemoveResult:
    """Result of remove_hook operation."""

    success: bool = False
    not_installed: bool = False
    message: str = ""


def remove_hook(scope: Scope, force: bool, ui: UI | None) -> RemoveResult:
    """Remove statuskit hook from settings.json.

    Args:
        scope: Installation scope to remove from
        force: Skip confirmation for foreign hooks
        ui: User interaction handler

    Returns:
        RemoveResult with operation details
    """
    settings_path = get_settings_path(scope)

    # Read current settings
    try:
        settings = read_settings(settings_path)
    except ValueError as e:
        return RemoveResult(success=False, message=str(e))

    current_hook = settings.get("statusLine", {})

    # Check if anything to remove
    if not current_hook.get("command"):
        return RemoveResult(
            success=True,
            not_installed=True,
            message="Not installed",
        )

    # Check if it's our hook
    if not is_our_hook(current_hook):
        foreign_cmd = current_hook.get("command", "")
        if force:
            pass  # proceed with removal
        elif ui:
            if not ui.confirm(
                f"statusLine points to: {foreign_cmd}\n"
                "Remove anyway?"
            ):
                return RemoveResult(success=False, message="Cancelled by user")
        else:
            return RemoveResult(
                success=False,
                message=f"Foreign hook: {foreign_cmd}. Use --force to remove.",
            )

    # Remove hook
    del settings["statusLine"]
    write_settings(settings_path, settings)

    return RemoveResult(success=True, message="Removed successfully")
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestRemoveHook -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/commands.py packages/statuskit/tests/test_setup_commands.py
git commit -m "feat(statuskit): add remove_hook command"
```

---

## Task 15: Add ConsoleUI for interactive prompts

**Files:**
- Create: `packages/statuskit/src/statuskit/setup/ui.py`
- Create: `packages/statuskit/tests/test_setup_ui.py`

**Step 1: Write failing tests for ConsoleUI**

```python
# packages/statuskit/tests/test_setup_ui.py
"""Tests for ConsoleUI."""

import pytest


class TestConsoleUI:
    """Tests for ConsoleUI class."""

    def test_confirm_yes(self, monkeypatch):
        """confirm returns True for 'y' input."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "y")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is True

    def test_confirm_no(self, monkeypatch):
        """confirm returns False for 'n' input."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "n")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is False

    def test_confirm_empty_default_no(self, monkeypatch):
        """confirm returns False for empty input (default no)."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "")
        ui = ConsoleUI()

        assert ui.confirm("Continue?") is False

    def test_choose_returns_index(self, monkeypatch, capsys):
        """choose returns selected option index."""
        from statuskit.setup.ui import ConsoleUI

        monkeypatch.setattr("builtins.input", lambda _: "2")
        ui = ConsoleUI()

        result = ui.choose("Select:", ["Option A", "Option B", "Cancel"])

        assert result == 1  # 0-based index for "2"
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_ui.py -v`
Expected: FAIL with ModuleNotFoundError

**Step 3: Create UI module**

```python
# packages/statuskit/src/statuskit/setup/ui.py
"""Console UI for setup command."""


class ConsoleUI:
    """Interactive console UI for setup command."""

    def confirm(self, message: str) -> bool:
        """Ask user for yes/no confirmation.

        Default is no (returns False for empty input).
        """
        response = input(f"{message} [y/N] ").strip().lower()
        return response in ("y", "yes")

    def choose(self, message: str, options: list[str]) -> int:
        """Ask user to choose from options.

        Returns 0-based index of selected option.
        """
        print(message)
        for i, option in enumerate(options, 1):
            print(f"{i}. {option}")

        while True:
            try:
                choice = int(input("Your choice: ").strip())
                if 1 <= choice <= len(options):
                    return choice - 1
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {len(options)}")
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_ui.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/ui.py packages/statuskit/tests/test_setup_ui.py
git commit -m "feat(statuskit): add ConsoleUI for interactive prompts"
```

---

## Task 16: Wire setup command into main()

**Files:**
- Modify: `packages/statuskit/src/statuskit/__init__.py`
- Modify: `packages/statuskit/tests/test_main.py`

**Step 1: Write failing test for setup command integration**

```python
# Add to packages/statuskit/tests/test_main.py

def test_main_setup_check(capsys, monkeypatch, tmp_path):
    """main() handles 'setup --check' command."""
    import sys

    # Mock home to tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", ["statuskit", "setup", "--check"])

    main()

    captured = capsys.readouterr()
    assert "User:" in captured.out
    assert "Not installed" in captured.out
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_main.py::test_main_setup_check -v`
Expected: FAIL

**Step 3: Update main() to handle setup command**

```python
# packages/statuskit/src/statuskit/__init__.py
"""Modular statusline kit for Claude Code."""

import json
import sys

from termcolor import colored

from .cli import create_parser
from .core.config import load_config
from .core.loader import load_modules
from .core.models import RenderContext, StatusInput


def main() -> None:
    """Entry point for statuskit command."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle setup command
    if args.command == "setup":
        from .setup.commands import check_installation, install_hook, remove_hook
        from .setup.paths import Scope
        from .setup.ui import ConsoleUI

        if args.check:
            print(check_installation())
            return

        scope = Scope(args.scope)
        ui = None if args.force else ConsoleUI()

        if args.remove:
            result = remove_hook(scope, force=args.force, ui=ui)
            if result.not_installed:
                print(f"statuskit is not installed at {scope.value} scope.")
            elif result.success:
                print(f"\u2713 Removed statusline hook from {scope.value} scope.")
            else:
                print(f"Error: {result.message}")
                sys.exit(1)
            return

        # Install
        result = install_hook(scope, force=args.force, ui=ui)
        if result.already_installed:
            print(f"statuskit is already installed at {scope.value} scope.")
            if result.config_created:
                print(f"\u2713 Created config file.")
        elif result.success:
            print(f"\u2713 Added statusline hook to {scope.value} scope.")
            if result.backup_created:
                print(f"\u2713 Created backup of previous settings.")
            if result.config_created:
                print(f"\u2713 Created config file.")
            print("\nRun `claude` to see your new statusline!")
        else:
            print(f"Error: {result.message}")
            sys.exit(1)
        return

    # Main mode: read from stdin
    if sys.stdin.isatty():
        print("statuskit: reads JSON from stdin")
        print("Usage: echo '{...}' | statuskit")
        print("\nRun 'statuskit setup' to configure Claude Code integration.")
        return

    config = load_config()

    try:
        raw_data = json.load(sys.stdin)
        data = StatusInput.from_dict(raw_data)
    except Exception as e:
        if config.debug:
            print(colored(f"[!] Failed to parse input: {e}", "red"))
        return

    ctx = RenderContext(debug=config.debug, data=data)
    modules = load_modules(config, ctx)

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

Run: `cd packages/statuskit && uv run pytest tests/test_main.py::test_main_setup_check -v`
Expected: PASS

**Step 5: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_main.py
git commit -m "feat(statuskit): wire setup command into main entry point"
```

---

## Task 17: Update config loading to support scope hierarchy

**Files:**
- Modify: `packages/statuskit/src/statuskit/core/config.py`
- Modify: `packages/statuskit/tests/test_config.py`

**Step 1: Write failing tests for hierarchical config loading**

```python
# Add to packages/statuskit/tests/test_config.py

class TestLoadConfigHierarchy:
    """Tests for hierarchical config loading."""

    def test_local_takes_priority(self, tmp_path, monkeypatch):
        """Local config overrides project and user."""
        from statuskit.core.config import load_config

        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        # Project config
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "statuskit.toml").write_text('modules = ["git"]')

        # Local config
        (project / ".claude" / "statuskit.local.toml").write_text('modules = ["quota"]')

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["quota"]

    def test_project_takes_priority_over_user(self, tmp_path, monkeypatch):
        """Project config overrides user."""
        from statuskit.core.config import load_config

        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        # Project config
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "statuskit.toml").write_text('modules = ["git"]')

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["git"]

    def test_user_used_when_no_project(self, tmp_path, monkeypatch):
        """User config used when no project config."""
        from statuskit.core.config import load_config

        home = tmp_path / "home"
        project = tmp_path / "project"

        # User config only
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "statuskit.toml").write_text('modules = ["model"]')

        project.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        config = load_config()

        assert config.modules == ["model"]
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_config.py::TestLoadConfigHierarchy -v`
Expected: FAIL

**Step 3: Update config loading**

```python
# packages/statuskit/src/statuskit/core/config.py
"""Configuration loading for statuskit."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from termcolor import colored


# Config paths in priority order (highest first)
def _get_config_paths() -> list[Path]:
    """Get config paths in priority order."""
    return [
        Path(".claude") / "statuskit.local.toml",  # Local (highest)
        Path(".claude") / "statuskit.toml",         # Project
        Path.home() / ".claude" / "statuskit.toml", # User (lowest)
    ]


@dataclass
class Config:
    """Statuskit configuration."""

    debug: bool = False
    modules: list[str] = field(default_factory=lambda: ["model", "git", "beads", "quota"])
    module_configs: dict[str, dict] = field(default_factory=dict)

    def get_module_config(self, name: str) -> dict:
        """Get configuration for a specific module."""
        return self.module_configs.get(name, {})


def load_config() -> Config:
    """Load configuration from TOML files.

    Searches in priority order:
    1. .claude/statuskit.local.toml (Local)
    2. .claude/statuskit.toml (Project)
    3. ~/.claude/statuskit.toml (User)

    Returns defaults if no config file exists.
    Shows error and returns defaults if file is invalid.
    """
    for config_path in _get_config_paths():
        if config_path.exists():
            try:
                with config_path.open("rb") as f:
                    data = tomllib.load(f)
            except (tomllib.TOMLDecodeError, OSError) as e:
                print(colored(f"[!] Config error in {config_path}: {e}", "red"))
                return Config()

            # Extract module configs
            module_configs = {
                k: v for k, v in data.items()
                if isinstance(v, dict) and k not in ("debug", "modules")
            }

            return Config(
                debug=data.get("debug", False),
                modules=data.get("modules", Config().modules),
                module_configs=module_configs,
            )

    return Config()
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_config.py::TestLoadConfigHierarchy -v`
Expected: PASS

**Step 5: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add packages/statuskit/src/statuskit/core/config.py packages/statuskit/tests/test_config.py
git commit -m "feat(statuskit): support hierarchical config loading"
```

---

## Task 18: Add higher-scope installation detection

**Files:**
- Modify: `packages/statuskit/src/statuskit/setup/commands.py`
- Modify: `packages/statuskit/tests/test_setup_commands.py`

**Step 1: Write failing tests for higher-scope detection**

```python
# Add to packages/statuskit/tests/test_setup_commands.py

class TestInstallHookHigherScope:
    """Tests for install_hook with higher-scope detection."""

    def test_detects_user_when_installing_project(self, tmp_path, monkeypatch):
        """Detects user scope installation when installing to project."""
        from statuskit.setup.commands import install_hook
        from statuskit.setup.paths import Scope
        import json

        home = tmp_path / "home"
        project = tmp_path / "project"

        # User already installed
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"statusLine": {"command": "statuskit"}})
        )

        project.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(project)

        result = install_hook(Scope.PROJECT, force=False, ui=None)

        assert result.higher_scope_installed is True
        assert result.higher_scope == Scope.USER
```

**Step 2: Run test to verify it fails**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHookHigherScope -v`
Expected: FAIL

**Step 3: Add higher-scope detection to install_hook**

```python
# Update InstallResult in packages/statuskit/src/statuskit/setup/commands.py

@dataclass
class InstallResult:
    """Result of install_hook operation."""

    success: bool = False
    already_installed: bool = False
    backup_created: bool = False
    config_created: bool = False
    higher_scope_installed: bool = False
    higher_scope: Scope | None = None
    message: str = ""


def _get_higher_scopes(scope: Scope) -> list[Scope]:
    """Get scopes higher than the given scope."""
    order = [Scope.LOCAL, Scope.PROJECT, Scope.USER]
    idx = order.index(scope)
    return order[idx + 1:]


def _check_higher_scope_installation(scope: Scope) -> Scope | None:
    """Check if statuskit is installed at a higher scope.

    Returns the higher scope if installed, None otherwise.
    """
    for higher_scope in _get_higher_scopes(scope):
        settings_path = get_settings_path(higher_scope)
        settings = read_settings(settings_path)
        if is_our_hook(settings.get("statusLine", {})):
            return higher_scope
    return None


def install_hook(scope: Scope, force: bool, ui: UI | None) -> InstallResult:
    """Install statuskit hook to settings.json."""
    settings_path = get_settings_path(scope)
    config_path = get_config_path(scope)

    # Check for higher scope installation
    higher_scope = _check_higher_scope_installation(scope)
    if higher_scope and not force:
        # Just create config, don't install hook (unless force)
        config_created = create_config(config_path)
        return InstallResult(
            success=True,
            higher_scope_installed=True,
            higher_scope=higher_scope,
            config_created=config_created,
            message=f"Already installed at {higher_scope.value} scope",
        )

    # ... rest of existing install_hook code ...
    try:
        settings = read_settings(settings_path)
    except ValueError as e:
        return InstallResult(success=False, message=str(e))

    current_hook = settings.get("statusLine", {})

    if is_our_hook(current_hook):
        config_created = create_config(config_path)
        return InstallResult(
            success=True,
            already_installed=True,
            config_created=config_created,
            message="Already installed",
        )

    backup_created = False
    if current_hook.get("command"):
        if force:
            create_backup(settings_path)
            backup_created = True
        elif ui:
            foreign_cmd = current_hook.get("command", "")
            if not ui.confirm(
                f"statusLine points to: {foreign_cmd}\n"
                "Overwrite? (backup will be created)"
            ):
                return InstallResult(success=False, message="Cancelled by user")
            create_backup(settings_path)
            backup_created = True
        else:
            return InstallResult(
                success=False,
                message=f"Foreign hook exists: {current_hook.get('command')}. Use --force to overwrite.",
            )

    settings["statusLine"] = {"type": "command", "command": "statuskit"}
    write_settings(settings_path, settings)

    config_created = create_config(config_path)

    return InstallResult(
        success=True,
        backup_created=backup_created,
        config_created=config_created,
        message="Installed successfully",
    )
```

**Step 4: Run test to verify it passes**

Run: `cd packages/statuskit && uv run pytest tests/test_setup_commands.py::TestInstallHookHigherScope -v`
Expected: PASS

**Step 5: Update main() to handle higher-scope message**

```python
# Update the install section in main() to show higher-scope message

        if result.higher_scope_installed:
            print(f"statuskit is already installed at {result.higher_scope.value} scope.")
            print("The hook will work for this project too.")
            if result.config_created:
                print(f"\u2713 Created config file at {scope.value} scope.")
```

**Step 6: Run all tests**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add packages/statuskit/src/statuskit/setup/commands.py packages/statuskit/src/statuskit/__init__.py packages/statuskit/tests/test_setup_commands.py
git commit -m "feat(statuskit): detect higher-scope installation"
```

---

## Task 19: Final integration test and build verification

**Files:**
- No new files, verification only

**Step 1: Run full test suite**

Run: `cd packages/statuskit && uv run pytest -v`
Expected: All tests pass

**Step 2: Run linter**

Run: `cd packages/statuskit && uv run ruff check .`
Expected: No errors

**Step 3: Build package**

Run: `cd packages/statuskit && uv build`
Expected: Successfully builds wheel

**Step 4: Test local install**

Run: `uv tool install packages/statuskit/dist/statuskit-0.1.0-py3-none-any.whl --force`
Expected: Successfully installs

**Step 5: Verify CLI commands**

Run:
```bash
statuskit --version
statuskit --help
statuskit setup --check
```
Expected: All commands work correctly

**Step 6: Commit final state**

```bash
git add -A
git commit -m "feat(statuskit): complete distribution setup with CLI and setup command"
```

---

## Summary

This plan implements:

1. **pyproject.toml metadata** — Full PyPI metadata for package publishing
2. **README.md** — Documentation for PyPI page
3. **CLI with argparse** — --help, --version, setup subcommand
4. **setup command** — --check, --remove, --scope, --force flags
5. **Scope hierarchy** — user/project/local config paths
6. **Hook detection** — is_our_hook for detecting existing installation
7. **Settings management** — read/write/backup utilities
8. **Config creation** — Default statuskit.toml generation
9. **Gitignore handling** — Auto-add .claude/*.local.* for local scope
10. **Higher-scope detection** — Warn when already installed at higher scope
11. **Interactive UI** — ConsoleUI for confirmations

Total: 19 tasks with TDD approach (test → implement → verify → commit)
