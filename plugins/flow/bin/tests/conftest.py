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


# --- review-loop wait helper: fake gh / glab -------------------------------

import json as _json  # noqa: E402  (local alias; module-level json used by callers too)

SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

_GH_FAKE = """#!/usr/bin/env python3
import sys, json
from pathlib import Path
STATE = Path({state!r})
a = sys.argv[1:]
if a[:2] == ["repo", "view"]:
    p = STATE / "repo"
    sys.stdout.write(p.read_text() if p.exists() else "o/r")
    sys.exit(0)
if a[:2] == ["api", "graphql"]:
    n = int((STATE / "count").read_text())
    (STATE / "count").write_text(str(n + 1))
    queue = json.loads((STATE / "queue").read_text())
    sys.stdout.write(queue[n] if n < len(queue) else queue[-1])
    sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def fake_gh(tmp_path):
    """Fake `gh` on PATH: `repo view` -> owner/repo; `api graphql` -> next queued response."""
    state = tmp_path / "gh-state"
    state.mkdir()
    (state / "count").write_text("0")
    (state / "queue").write_text("[]")
    gh = tmp_path / "gh"
    gh.write_text(_GH_FAKE.format(state=str(state)))
    gh.chmod(0o755)

    class Ctl:
        dir = state

        def env(self, **overrides):
            base = {
                "PATH": f"{tmp_path}:/usr/bin:/bin",
                "WAIT_INTERVAL": "0",
                "WAIT_TIMEOUT": "30",
                "WAIT_GRACE": "30",
            }
            base.update(overrides)
            return base

        def set_repo(self, nwo):
            (state / "repo").write_text(nwo)

        def queue(self, responses):
            (state / "queue").write_text(_json.dumps(list(responses)))
            (state / "count").write_text("0")

        def poll_count(self):
            return int((state / "count").read_text())

    return Ctl()


def gh_response(*, nodes=None, merge="CLEAN", head=SHA, rollup_state="SUCCESS", rollup=True):
    """Build one GitHub `statusCheckRollup` GraphQL response string.

    nodes: list of ("check", name, status, conclusion) or ("status", context, state).
    rollup=False emits a null rollup (fresh head / no checks registered).
    """
    if not rollup:
        obj = {"statusCheckRollup": None}
    else:
        check_counts, status_counts, node_list = {}, {}, []
        for n in nodes or []:
            if n[0] == "check":
                _, name, st, concl = n
                node_list.append({"__typename": "CheckRun", "name": name, "status": st, "conclusion": concl})
                check_counts[st] = check_counts.get(st, 0) + 1
            else:
                _, ctx, state = n
                node_list.append({"__typename": "StatusContext", "context": ctx, "state": state})
                status_counts[state] = status_counts.get(state, 0) + 1
        obj = {
            "statusCheckRollup": {
                "state": rollup_state,
                "contexts": {
                    "checkRunCount": sum(check_counts.values()),
                    "checkRunCountsByState": [{"state": k, "count": v} for k, v in check_counts.items()],
                    "statusContextCount": sum(status_counts.values()),
                    "statusContextCountsByState": [{"state": k, "count": v} for k, v in status_counts.items()],
                    "nodes": node_list,
                },
            }
        }
    return _json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {"mergeStateStatus": merge, "headRefOid": head},
                    "object": obj,
                }
            }
        }
    )
