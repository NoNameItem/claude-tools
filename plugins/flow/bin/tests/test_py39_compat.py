"""Regression: bin/ helpers must import under Python 3.9 (no runtime PEP 604 unions).

Guards claude-tools-dsc. PEP 604 unions (`str | None`) in function signatures and
@dataclass bodies are evaluated at import time; under Python < 3.10 that raises
TypeError before the script reads stdin. `from __future__ import annotations` makes
annotations lazy. Ruff's FA102, under a py39 target, flags any helper that uses a
PEP 604 union without that future import.
"""

# bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent


def test_helpers_compatible_with_py39():
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff not on PATH")
    helpers = sorted(str(p) for p in (*BIN.glob("flow-*"), *BIN.glob("_*.py")) if p.is_file())
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


def test_reply_order_parses_a_z_suffix_on_a_real_pre311_interpreter():
    """`datetime.fromisoformat` learned the bare `Z` only in 3.11, so `_ledger.reply_order`
    rewrites it to `+00:00` before parsing. Every other test of that rewrite runs on CI's 3.11+,
    where the assertion holds with or without it -- this is the only check that can actually fail
    if the rewrite is removed, and what it protects is the thread sort silently degrading to a
    no-op on exactly the interpreters CI never exercises."""
    python = _find_pre311_python()
    if python is None:
        pytest.skip("no Python < 3.11 interpreter found on PATH")
    result = subprocess.run(
        [
            python,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import _ledger; "
            "print(_ledger.reply_order({'created_at': '2026-07-20T10:00:00Z'})[0])",
            str(BIN),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # Bucket 0 means the timestamp parsed; bucket 1 is the "unusable, sink to the tail" fallback
    # every reply would land in if the `Z` never became `+00:00`.
    assert result.stdout.strip() == "0", f"Z suffix did not parse under {python}: {result.stdout!r}"
