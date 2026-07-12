"""Regression: bin/ helpers must import under Python 3.9 (no runtime PEP 604 unions).

Guards claude-tools-dsc. PEP 604 unions (`str | None`) in function signatures and
@dataclass bodies are evaluated at import time; under Python < 3.10 that raises
TypeError before the script reads stdin. `from __future__ import annotations` makes
annotations lazy. Ruff's FA102, under a py39 target, flags any helper that uses a
PEP 604 union without that future import.
"""

# ruff: noqa: INP001

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
