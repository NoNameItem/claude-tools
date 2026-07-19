"""Regression: bin/ helpers must import under Python 3.9 (no runtime PEP 604 unions).

Guards claude-tools-dsc. PEP 604 unions (`str | None`) in function signatures and
@dataclass bodies are evaluated at import time; under Python < 3.10 that raises
TypeError before the script reads stdin. `from __future__ import annotations` makes
annotations lazy. Ruff's FA102, under a py39 target, flags any helper that uses a
PEP 604 union without that future import.

`flow-codex-agent-setup` / `_codex_agents.py` are the one documented, deliberate exception:
they hard-require Python 3.11 for `tomllib` (an optional Codex profile setup helper, not part
of the core Flow workflow), so they are excluded from the FA102 sweep above and are instead
covered by `test_py311_exception_degrades_gracefully` below, which proves — on a real pre-3.11
interpreter when one is available on PATH — that they exit with a concise diagnostic instead of
a raw import traceback, and never affect any other helper.
"""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent

PY311_EXCEPTIONS = frozenset({"flow-codex-agent-setup", "_codex_agents.py"})


def test_helpers_compatible_with_py39():
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff not on PATH")
    helpers = sorted(
        str(p) for p in (*BIN.glob("flow-*"), *BIN.glob("_*.py")) if p.is_file() and p.name not in PY311_EXCEPTIONS
    )
    assert helpers, "no flow-* or _*.py helpers found"
    result = subprocess.run(
        [ruff, "check", "--select", "FA102", "--target-version", "py39", "--no-cache", *helpers],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "ruff FA102 found PEP 604 unions missing the future import "
        f"(crashes at import under Python < 3.10):\n{result.stdout}{result.stderr}"
    )


def test_py311_exception_set_matches_real_files():
    """Guards the exception list itself: both documented files must exist, and this test
    must not silently grow into an escape hatch for an unrelated helper."""
    for name in PY311_EXCEPTIONS:
        assert (BIN / name).is_file(), f"documented 3.11 exception {name!r} is missing"
    assert PY311_EXCEPTIONS == {"flow-codex-agent-setup", "_codex_agents.py"}


def _find_pre311_python() -> str | None:
    """First Python < 3.11 interpreter found on PATH, or None if none is available."""
    for candidate in ("python3.9", "python3.10", "python3.8", "python3"):
        found = shutil.which(candidate)
        if found is None:
            continue
        probe = subprocess.run(
            [found, "-c", "import sys; print(list(sys.version_info[:2]))"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            continue
        try:
            major, minor = ast.literal_eval(probe.stdout.strip())
        except (ValueError, SyntaxError):
            continue
        if (major, minor) < (3, 11):
            return found
    return None


def test_py311_exception_degrades_gracefully():
    """On a real pre-3.11 interpreter, the setup helper must exit nonzero with a concise
    stderr diagnostic -- not a raw `ModuleNotFoundError: tomllib` traceback -- and this must
    not require or affect any other Flow helper."""
    python = _find_pre311_python()
    if python is None:
        pytest.skip("no Python < 3.11 interpreter found on PATH")
    result = subprocess.run(
        [python, str(BIN / "flow-codex-agent-setup"), "inspect", "--project-root", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "3.11" in result.stderr
    assert "Traceback" not in result.stderr
