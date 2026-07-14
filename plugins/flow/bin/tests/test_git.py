"""Tests for _git.py (shared git/gh/glab CLI foundation)."""

# ruff: noqa: INP001  # bin/tests/ has no __init__.py (pytest rootdir layout)

import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import _git  # noqa: E402  (import after BIN is on sys.path — sibling-module pattern)


class TestHostFromRemote:
    def test_ssh_form(self):
        assert _git.host_from_remote("git@github.com:o/r.git") == "github.com"

    def test_https_form(self):
        assert _git.host_from_remote("https://gitlab.example.com/g/r.git") == "gitlab.example.com"

    def test_https_no_dot_git(self):
        assert _git.host_from_remote("https://github.com/o/r") == "github.com"

    def test_ssh_subgroup(self):
        assert _git.host_from_remote("git@gitlab.example.com:g/sub/r.git") == "gitlab.example.com"

    def test_https_strips_userinfo(self):
        # Token in the URL must NOT leak into the host (credential leak + breaks exact-match).
        url = "https://oauth2:TOKEN@git.angara.cloud/g/r.git"
        assert _git.host_from_remote(url) == "git.angara.cloud"

    def test_unparseable_returns_none(self):
        assert _git.host_from_remote("not-a-url") is None

    def test_ssh_scheme_without_port(self):
        # ssh:// with no explicit port: the scp-form regex misses it (no ':' after host).
        assert _git.host_from_remote("ssh://git@github.com/o/r.git") == "github.com"

    def test_ssh_scheme_with_port_keeps_port(self):
        # Port is intentionally preserved for now (host:port normalization is a follow-up).
        assert _git.host_from_remote("ssh://git@ghe.example.com:22/o/r.git") == "ghe.example.com:22"

    def test_ssh_scheme_strips_userinfo(self):
        assert _git.host_from_remote("ssh://git@gitlab.example.com/g/sub/r.git") == "gitlab.example.com"


class TestDecidePlatform:
    def test_override_wins(self):
        assert _git.decide_platform("gitlab", "github.com", ["github.com"], []) == "gitlab"

    def test_host_in_gh_auth(self):
        assert _git.decide_platform(None, "ghe.corp", ["ghe.corp"], []) == "github"

    def test_host_in_glab_auth(self):
        assert _git.decide_platform(None, "gl.corp", [], ["gl.corp"]) == "gitlab"

    def test_heuristic_github(self):
        assert _git.decide_platform(None, "github.example", [], []) == "github"

    def test_heuristic_gitlab(self):
        assert _git.decide_platform(None, "gitlab.example", [], []) == "gitlab"

    def test_undecidable_raises(self):
        with pytest.raises(ValueError, match="cannot determine platform"):
            _git.decide_platform(None, "bitbucket.org", [], [])


class TestRunAndResolve:
    def test_run_returns_stripped_stdout(self, tmp_path):
        script = tmp_path / "echoer"
        script.write_text("#!/usr/bin/env python3\nprint('  hello  ')\n")
        script.chmod(0o755)
        assert _git.run([str(script)]) == "hello"

    def test_run_raises_on_nonzero_when_check(self, tmp_path):
        script = tmp_path / "boom"
        script.write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n")
        script.chmod(0o755)
        with pytest.raises(subprocess.CalledProcessError):
            _git.run([str(script)])

    def test_resolve_repo_via_fake_gh(self, tmp_path, monkeypatch):
        gh = tmp_path / "gh"
        gh.write_text("#!/usr/bin/env python3\nprint('acme/widgets')\n")
        gh.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        assert _git.resolve_repo() == "acme/widgets"
        # Callers (flow-wait-ci) pass a custom timeout; the kwarg must be accepted and forwarded.
        assert _git.resolve_repo(timeout=5) == "acme/widgets"

    def test_resolve_project_url_encodes_subgroup(self, tmp_path, monkeypatch):
        glab = tmp_path / "glab"
        glab.write_text('#!/usr/bin/env python3\nprint(\'{"path_with_namespace": "group/sub/repo"}\')\n')
        glab.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        assert _git.resolve_project() == "group%2Fsub%2Frepo"
        # Callers (flow-wait-ci) pass a custom timeout; the kwarg must be accepted and forwarded.
        assert _git.resolve_project(timeout=5) == "group%2Fsub%2Frepo"


class TestGhApiSlurp:
    # C68: `gh api --paginate` (no `--slurp`) emits each page as its own top-level JSON
    # array, so a multi-page PR breaks `json.loads` with "Extra data". `--slurp` wraps all
    # pages into one outer array, but is incompatible with `-q`/`--jq`.
    def test_paginate_and_slurp_both_present_in_order(self, monkeypatch):
        captured = {}

        def fake_run(argv, **_kw):
            captured["argv"] = argv
            return "[]"

        monkeypatch.setattr(_git, "run", fake_run)
        _git.gh_api("repos/o/r/pulls/1/comments", paginate=True, slurp=True)
        argv = captured["argv"]
        assert "--paginate" in argv
        assert "--slurp" in argv
        assert argv.index("--paginate") < argv.index("--slurp")

    def test_slurp_and_jq_are_mutually_exclusive(self):
        with pytest.raises(ValueError, match="slurp and jq"):
            _git.gh_api("user", slurp=True, jq=".login")


class TestApiWrappers:
    def test_glab_api_never_emits_q_flag(self, monkeypatch):
        # `glab api` has NO -q/--jq flag; the wrapper must never add one (a stray -q makes
        # glab error on an unknown flag). Capture the argv it hands to run().
        captured = {}

        def fake_run(argv, **_kw):
            captured["argv"] = argv
            return "{}"

        monkeypatch.setattr(_git, "run", fake_run)
        _git.glab_api("user")
        assert captured["argv"] == ["glab", "api", "user"]
        _git.glab_api("projects/x/merge_requests/1/discussions", paginate=True)
        assert "-q" not in captured["argv"]
        assert "--jq" not in captured["argv"]

    def test_glab_api_signature_has_no_jq(self):
        import inspect

        assert "jq" not in inspect.signature(_git.glab_api).parameters


class TestAuthHosts:
    def test_reads_host_from_stderr_on_nonzero_exit(self, tmp_path, monkeypatch):
        # Regression: `gh`/`glab auth status` write the host report to STDERR and may
        # exit non-zero (stale token). `_auth_hosts` must still return the host.
        gh = tmp_path / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'sys.stderr.write("ghe.corp\\n  x ghe.corp: API call failed\\n")\n'
            "sys.exit(1)\n"
        )
        gh.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        assert "ghe.corp" in _git._auth_hosts("gh")

    def test_missing_cli_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))  # no gh/glab on PATH
        assert _git._auth_hosts("gh") == []


class TestDetectPlatform:
    def test_detects_gitlab_via_remote_heuristic(self, tmp_path, monkeypatch):
        # Fake `git remote get-url origin` → a self-hosted host whose name contains
        # "gitlab"; no gh/glab auth match, so the heuristic decides.
        git = tmp_path / "git"
        git.write_text("#!/usr/bin/env python3\nprint('git@gitlab.example.com:g/r.git')\n")
        git.chmod(0o755)
        # Stub auth CLIs to return nothing so only the remote host drives the decision.
        for name in ("gh", "glab"):
            cli = tmp_path / name
            cli.write_text("#!/usr/bin/env python3\n")
            cli.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        assert _git.detect_platform() == "gitlab"

    def test_override_short_circuits(self, monkeypatch):
        # An explicit override must win with no CLI calls at all.
        monkeypatch.setenv("PATH", "/nonexistent")
        assert _git.detect_platform("github") == "github"
