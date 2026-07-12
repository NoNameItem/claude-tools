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

    def test_unparseable_returns_none(self):
        assert _git.host_from_remote("not-a-url") is None


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
