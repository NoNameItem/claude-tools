"""Tests for flow-require-bd (version guard)."""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from conftest import run_helper

BASE_ENV = {"PATH": "/usr/bin:/bin"}


def make_fake_bd(tmp_path, *, version_line=None):
    """Write a fake `bd` whose `version` subcommand prints version_line.

    version_line=None -> `bd version` exits non-zero (simulates failure).
    """
    bd = tmp_path / "bd"
    if version_line is None:
        body = "import sys\nsys.exit(1)\n"
    else:
        body = (
            "import sys\n"
            "if sys.argv[1:2] == ['version']:\n"
            f"    sys.stdout.write({version_line!r})\n"
            "    sys.exit(0)\n"
            "sys.exit(0)\n"
        )
    bd.write_text("#!/usr/bin/env python3\n" + body)
    bd.chmod(0o755)
    return bd


def test_supported_version_is_silent(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="bd version 1.0.5 (abc123)\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


def test_exact_minimum_is_accepted(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="bd version 1.0.0 (x)\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 0


def test_version_suffix_uses_numeric_part(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="bd version 1.1.0-rc.1 (x)\n")
    # The semver regex intentionally ignores the `-rc.1` suffix and parses (1, 1, 0).
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 0


def test_version_anchored_to_version_keyword(tmp_path):
    # A stray triple before the real version must not be picked up: the regex
    # anchors to the `version` token, so it parses (1, 0, 5), not (0, 0, 1).
    bd = make_fake_bd(tmp_path, version_line="meta 0.0.1\nbd version 1.0.5 (x)\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 0


def test_old_version_rejected_with_message(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="bd version 0.47.1 (x)\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 1
    assert "1.0.0" in r.stderr  # required version named
    assert "0.47.1" in r.stderr  # found version named
    assert str(bd) in r.stderr  # resolved path shown (PATH-shadowing visibility)


def test_homebrew_culprit_0_44_rejected(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="bd version 0.44.0 (x)\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 1
    assert "0.44.0" in r.stderr


def test_unparseable_version_rejected(tmp_path):
    bd = make_fake_bd(tmp_path, version_line="totally not a version\n")
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 3
    assert "1.0.0" in r.stderr


def test_version_command_failure_rejected(tmp_path):
    bd = make_fake_bd(tmp_path, version_line=None)  # `bd version` exits 1
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(bd)})
    assert r.returncode == 3


def test_bd_not_found(tmp_path):
    missing = tmp_path / "nope-bd"
    r = run_helper("flow-require-bd", env={**BASE_ENV, "BD_BIN": str(missing)})
    assert r.returncode == 2
    assert "1.0.0" in r.stderr
