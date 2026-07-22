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

# GitHub returns EVERY enum state in checkRun/statusContext CountsByState (count=0 for absent
# states), so a fixture that emits only non-zero states hides the "key vs count" bug
# (claude-tools-r1r). Seed the active states (mirroring flow-wait-ci's GH_ACTIVE_*_STATES) at 0
# so an all-terminal rollup still carries them; real counts from `nodes` overlay on top.
_GH_ZERO_CHECK_STATES = ("REQUESTED", "QUEUED", "IN_PROGRESS", "WAITING", "PENDING")
_GH_ZERO_STATUS_STATES = ("EXPECTED", "PENDING")

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
                "WAIT_TIMEOUT": "5",
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
                    "checkRunCountsByState": [
                        {"state": s, "count": check_counts.get(s, 0)}
                        for s in {**dict.fromkeys(_GH_ZERO_CHECK_STATES, 0), **check_counts}
                    ],
                    "statusContextCount": sum(status_counts.values()),
                    "statusContextCountsByState": [
                        {"state": s, "count": status_counts.get(s, 0)}
                        for s in {**dict.fromkeys(_GH_ZERO_STATUS_STATES, 0), **status_counts}
                    ],
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


_GLAB_FAKE = """#!/usr/bin/env python3
import sys, json
from pathlib import Path
STATE = Path({state!r})
a = sys.argv[1:]
if a[:2] == ["repo", "view"]:
    p = STATE / "project"
    path = p.read_text() if p.exists() else "g/r"
    sys.stdout.write(json.dumps({{"path_with_namespace": path}}))
    sys.exit(0)
if a and a[0] == "api":
    ep = a[1] if len(a) > 1 else ""
    if "/jobs" in ep:
        p = STATE / "jobs"
        sys.stdout.write(p.read_text() if p.exists() else "[]")
        sys.exit(0)
    n = int((STATE / "count").read_text())
    (STATE / "count").write_text(str(n + 1))
    queue = json.loads((STATE / "queue").read_text())
    sys.stdout.write(queue[n] if n < len(queue) else queue[-1])
    sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def fake_glab(tmp_path):
    """Fake `glab` on PATH: `repo view` -> project path; `api .../merge_requests/iid` ->
    next queued MR response; `api .../jobs...` -> the canned failed-jobs list."""
    state = tmp_path / "glab-state"
    state.mkdir()
    (state / "count").write_text("0")
    (state / "queue").write_text("[]")
    glab = tmp_path / "glab"
    glab.write_text(_GLAB_FAKE.format(state=str(state)))
    glab.chmod(0o755)

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

        def set_project(self, path):
            (state / "project").write_text(path)

        def queue(self, responses):
            (state / "queue").write_text(_json.dumps(list(responses)))
            (state / "count").write_text("0")

        def set_jobs(self, response):
            (state / "jobs").write_text(response)

        def poll_count(self):
            return int((state / "count").read_text())

    return Ctl()


def gl_mr(*, status="success", head=SHA, pipeline_sha=None, pid=1, present=True):
    """Build one GitLab MR response string (`glab api .../merge_requests/:iid`).

    head = MR diff head sha; pipeline_sha defaults to head; present=False -> no pipeline yet.
    For a head-moved case set head != SHA but pipeline_sha == SHA (the pipeline for the
    requested sha finished, but the MR head advanced).
    """
    pipeline = None
    if present:
        pipeline = {"id": pid, "sha": pipeline_sha or head, "status": status}
    return _json.dumps({"sha": head, "head_pipeline": pipeline})


def gl_jobs(*jobs):
    """Build a failed-jobs list. Each job is (name, allow_failure)."""
    return _json.dumps([{"name": n, "status": "failed", "allow_failure": af} for (n, af) in jobs])


# --- review-collect fakes: route `gh`/`glab` by argv to canned per-endpoint files ------
#
# NOTE: `_git.gh_api` builds argv as ["gh", "api", "--paginate"?, <path>, "-q", <jq>?] and
# `_git.glab_api` as ["glab", "api", "--paginate"?, <path>] (glab has no `-q`/`--jq` flag).
# The `--paginate` flag (when present) comes BEFORE the path, not after. The `endpoint()`
# helper below walks past known flags (and their values) to find the first positional token,
# so routing is correct whether or not `paginate=True` was passed.

_GH_ROUTER = r"""#!/usr/bin/env python3
import sys, json
from pathlib import Path
STATE = Path({state!r})
a = sys.argv[1:]

def emit(name, default="[]"):
    p = STATE / name
    sys.stdout.write(p.read_text() if p.exists() else default)

# emit_pages: emits canned `name` the way real `gh api [--paginate] [--slurp]` would.
# Canned content is either a plain JSON value (the common single-page case) or
# {{"__pages__": [page1, page2, ...]}} to simulate a multi-page response. `--slurp`
# wraps every page into one outer array; without it, `gh api --paginate` emits each
# page as its own back-to-back top-level JSON document (no separator) -- which is
# exactly the multi-page bug (`json.loads`: "Extra data") this fixture reproduces.
def emit_pages(name, slurp, default="[]"):
    p = STATE / name
    raw = p.read_text() if p.exists() else default
    data = json.loads(raw)
    pages = data["__pages__"] if isinstance(data, dict) and "__pages__" in data else [data]
    if slurp:
        sys.stdout.write(json.dumps(pages))
    else:
        sys.stdout.write("".join(json.dumps(pg) for pg in pages))

def endpoint(rest):
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("--paginate", "--slurp"):
            i += 1
            continue
        if tok == "-q":
            i += 2
            continue
        return tok
    return ""

EMPTY_THREADS = (
    '{{"data":{{"repository":{{"pullRequest":{{"reviewThreads":'
    '{{"nodes":[],"pageInfo":{{"hasNextPage":false,"endCursor":null}}}}}}}}}}}}'
)

if a[:2] == ["pr", "view"]:
    emit("pr_view", "{{}}"); sys.exit(0)
if a[:2] == ["repo", "view"]:
    emit("repo", "o/r"); sys.exit(0)
if a[:1] == ["api"]:
    rest = a[1:]
    # `gh api user -q .login`
    if "user" in rest:
        emit("user", "me"); sys.exit(0)
    slurp = "--slurp" in rest
    ep = endpoint(rest)
    if ep == "graphql":
        emit("review_threads", EMPTY_THREADS)
        sys.exit(0)
    if ep.endswith("/comments"):
        emit_pages("comments", slurp); sys.exit(0)
    if ep.endswith("/reviews"):
        emit_pages("reviews", slurp); sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def fake_gh_api(tmp_path):
    """Fake `gh` routing each endpoint to a canned file the test writes."""
    state = tmp_path / "gh-api-state"
    state.mkdir()
    gh = tmp_path / "gh"
    gh.write_text(_GH_ROUTER.format(state=str(state)))
    gh.chmod(0o755)

    class Ctl:
        dir = state

        def env(self, **overrides):
            base = {"PATH": f"{tmp_path}:/usr/bin:/bin"}
            base.update(overrides)
            return base

        def set(self, name, text):
            (state / name).write_text(text)

    return Ctl()


_GLAB_ROUTER = r"""#!/usr/bin/env python3
import sys, json
from pathlib import Path
STATE = Path({state!r})
a = sys.argv[1:]

def emit(name, default="[]"):
    p = STATE / name
    sys.stdout.write(p.read_text() if p.exists() else default)

def endpoint(rest):
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--paginate":
            i += 1
            continue
        if tok == "-q":
            i += 2
            continue
        return tok
    return ""

if a[:2] == ["repo", "view"]:
    p = STATE / "project"
    path = p.read_text() if p.exists() else "g/r"
    sys.stdout.write(json.dumps({{"path_with_namespace": path}})); sys.exit(0)
if a[:2] == ["mr", "view"]:
    emit("mr_view", "{{}}"); sys.exit(0)
if a[:1] == ["api"]:
    rest = a[1:]
    if "user" in rest:
        emit("user", '{{"username": "me"}}'); sys.exit(0)  # glab api user -> JSON (no -q flag)
    ep = endpoint(rest)
    if ep.endswith("/discussions"):
        emit("discussions"); sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def fake_glab_api(tmp_path):
    """Fake `glab` routing each endpoint to a canned file the test writes."""
    state = tmp_path / "glab-api-state"
    state.mkdir()
    glab = tmp_path / "glab"
    glab.write_text(_GLAB_ROUTER.format(state=str(state)))
    glab.chmod(0o755)

    class Ctl:
        dir = state

        def env(self, **overrides):
            base = {"PATH": f"{tmp_path}:/usr/bin:/bin"}
            base.update(overrides)
            return base

        def set(self, name, text):
            (state / name).write_text(text)

    return Ctl()
