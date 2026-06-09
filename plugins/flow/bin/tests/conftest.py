"""Shared fixtures for flow bin/ helper tests."""

# ruff: noqa: INP001, PLW1510  # PLW1510: check IS passed via **common (false positive)

import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

BIN = Path(__file__).parent.parent


def run_helper(name, *args, cwd=None, env=None, stdin=None):
    """Run a bin/ helper via the current interpreter; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(BIN / name), *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def fake_bd(tmp_path):
    """Write a fake `bd` executable that serves canned JSON and captures updates.

    Returns a controller with:
      - env: dict to pass as the helper's environment (BD_BIN set)
      - set_show(json_str): canned stdout for `bd show ... --json` and `bd list --json`
      - captured_description(): the --description value from the last `bd update`
    """
    bd_path = tmp_path / "fake-bd"
    show_file = tmp_path / "show.json"
    capture_file = tmp_path / "update-description.txt"
    show_file.write_text("[]")

    bd_path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"SHOW = {str(show_file)!r}\n"
        f"CAPTURE = {str(capture_file)!r}\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] in ('show', 'list'):\n"
        "    sys.stdout.write(open(SHOW).read())\n"
        "elif args and args[0] == 'update':\n"
        "    if '--description' in args:\n"
        "        val = args[args.index('--description') + 1]\n"
        "        open(CAPTURE, 'w').write(val)\n"
        "    sys.exit(0)\n"
        "else:\n"
        "    sys.exit(0)\n"
    )
    bd_path.chmod(0o755)

    class Ctl:
        env: ClassVar[dict[str, str]] = {"BD_BIN": str(bd_path), "PATH": "/usr/bin:/bin"}

        def set_show(self, json_str):
            show_file.write_text(json_str)

        def captured_description(self):
            return capture_file.read_text() if capture_file.exists() else None

    return Ctl()


@pytest.fixture
def git_repo(tmp_path):
    """Init an empty git repo at tmp_path on branch `master`; return its Path."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(
        ["git", "init", "-q", "-b", "master", str(tmp_path)], check=True, env={**env, "PATH": "/usr/bin:/bin"}
    )
    (tmp_path / "f").write_text("x")
    common = {"cwd": tmp_path, "check": True, "env": {**env, "PATH": "/usr/bin:/bin"}}
    subprocess.run(["git", "add", "."], **common)
    subprocess.run(["git", "commit", "-qm", "init"], **common)
    return tmp_path
