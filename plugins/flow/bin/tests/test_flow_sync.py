"""Tests for flow-sync."""

# ruff: noqa: INP001

from pathlib import Path

from conftest import run_helper


def _fake_bd(tmp_path: Path, *, remote: bool, op_fails: bool = False, detect_errors: bool = False):
    """Write a fake `bd` that logs argv and simulates dolt remote/pull/push.

    Returns (env, calls_path). `calls_path` accumulates one line per invocation.
    """
    bd_path = tmp_path / "fake-bd"
    calls = tmp_path / "calls.txt"
    bd_path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"CALLS = {str(calls)!r}\n"
        f"REMOTE = {remote!r}\n"
        f"OP_FAILS = {op_fails!r}\n"
        f"DETECT_ERRORS = {detect_errors!r}\n"
        "args = sys.argv[1:]\n"
        "open(CALLS, 'a').write(' '.join(args) + '\\n')\n"
        "if args[:2] == ['dolt', 'remote']:\n"
        "    if DETECT_ERRORS:\n"
        "        sys.stderr.write('unknown command \"dolt\"\\n')\n"
        "        sys.exit(1)\n"
        "    if REMOTE:\n"
        "        sys.stdout.write('origin\\n')\n"
        "    sys.exit(0)\n"
        "if args[:2] in (['dolt', 'pull'], ['dolt', 'push']):\n"
        "    if OP_FAILS:\n"
        "        sys.stderr.write('network unreachable\\n')\n"
        "        sys.exit(1)\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n"
    )
    bd_path.chmod(0o755)
    env = {"BD_BIN": str(bd_path), "PATH": "/usr/bin:/bin"}
    return env, calls


def test_pull_with_remote_runs_dolt_pull(tmp_path):
    env, calls = _fake_bd(tmp_path, remote=True)
    r = run_helper("flow-sync", "pull", env=env)
    assert r.returncode == 0
    assert r.stderr == ""
    log = calls.read_text()
    assert "dolt remote" in log
    assert "dolt pull" in log


def test_push_with_remote_runs_dolt_push(tmp_path):
    env, calls = _fake_bd(tmp_path, remote=True)
    r = run_helper("flow-sync", "push", env=env)
    assert r.returncode == 0
    assert r.stderr == ""
    assert "dolt push" in calls.read_text()


def test_no_remote_skips_op_and_notes(tmp_path):
    env, calls = _fake_bd(tmp_path, remote=False)
    r = run_helper("flow-sync", "pull", env=env)
    assert r.returncode == 0
    assert "remote" in r.stderr.lower()
    log = calls.read_text()
    assert "dolt remote" in log
    assert "dolt pull" not in log  # op skipped when no remote


def test_detection_error_treated_as_no_remote(tmp_path):
    # Simulates old bd (no `dolt` subcommand): detect command errors out.
    env, calls = _fake_bd(tmp_path, remote=True, detect_errors=True)
    r = run_helper("flow-sync", "push", env=env)
    assert r.returncode == 0
    assert "remote" in r.stderr.lower()
    assert "dolt push" not in calls.read_text()


def test_op_failure_is_non_blocking(tmp_path):
    env, _ = _fake_bd(tmp_path, remote=True, op_fails=True)
    r = run_helper("flow-sync", "push", env=env)
    assert r.returncode == 0  # never blocks the skill
    assert "push" in r.stderr.lower()


def test_invalid_action_rejected(tmp_path):
    env, _ = _fake_bd(tmp_path, remote=True)
    r = run_helper("flow-sync", "frobnicate", env=env)
    assert r.returncode != 0  # argparse rejects unknown choice
