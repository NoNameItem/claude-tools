"""Shared git/gh/glab CLI foundation for flow bin/ helpers.

Injection-safe by construction: `run` takes an argv LIST that no shell parses, so a
reviewer-controlled path/title can never become command source. Split into pure decision
helpers (unit-tested) and thin IO wrappers (exercised through `run`). Home for future git
utilities too.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse

DEFAULT_TIMEOUT = 30

_SSH_RE = re.compile(r"^[^@]+@([^:]+):")
_HTTPS_RE = re.compile(r"^https?://(?:[^@/]+@)?([^/]+)/")


def run(argv: list[str], *, timeout: int = DEFAULT_TIMEOUT, check: bool = True) -> str:
    """Run a CLI as an argv list; return stripped stdout. Never invokes a shell.

    Propagates subprocess.CalledProcessError / TimeoutExpired so callers that want a
    retry loop (flow-wait-ci) can catch, and callers that want a hard failure
    (flow-review-collect) can let it abort.
    """
    proc = subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout)
    return proc.stdout.strip()


def host_from_remote(url: str) -> str | None:
    """Extract the host from an SSH or HTTPS git remote URL; None if unparseable."""
    m = _SSH_RE.match(url) or _HTTPS_RE.match(url)
    return m.group(1) if m else None


def _auth_hosts(cli: str) -> list[str]:
    """Hosts `cli` (`gh`/`glab`) is authenticated for; [] on any failure (never raises).

    `gh`/`glab auth status` write their report to STDERR (and exit non-zero when a token
    is stale), so this bypasses `run()` (stdout-only, check=True) and scans both streams.
    """
    try:
        proc = subprocess.run(
            [cli, "auth", "status"], capture_output=True, text=True, check=False, timeout=DEFAULT_TIMEOUT
        )
    except (subprocess.SubprocessError, OSError):
        return []
    out = f"{proc.stdout}\n{proc.stderr}"
    hosts = []
    for tok in re.findall(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", out):
        if tok not in hosts:
            hosts.append(tok)
    return hosts


def decide_platform(override: str | None, remote_host: str | None, gh_hosts: list[str], glab_hosts: list[str]) -> str:
    """Pure platform decision (Phase-0 algorithm). Raises ValueError if undecidable."""
    if override in ("github", "gitlab"):
        return override
    if remote_host:
        low = remote_host.lower()
        if low in {h.lower() for h in gh_hosts}:
            return "github"
        if low in {h.lower() for h in glab_hosts}:
            return "gitlab"
        if "github" in low:
            return "github"
        if "gitlab" in low:
            return "gitlab"
    msg = f"cannot determine platform for remote host {remote_host!r}; pass --platform"
    raise ValueError(msg)


def detect_platform(override: str | None = None) -> str:
    """Resolve the platform via override → remote host → gh/glab auth → heuristic."""
    remote_host = None
    try:
        remote_host = host_from_remote(run(["git", "remote", "get-url", "origin"]))
    except (subprocess.SubprocessError, OSError):
        pass
    return decide_platform(override, remote_host, _auth_hosts("gh"), _auth_hosts("glab"))


def resolve_repo(*, timeout: int = DEFAULT_TIMEOUT) -> str:
    """GitHub 'owner/repo' for the current repo."""
    return run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], timeout=timeout)


def resolve_project(*, timeout: int = DEFAULT_TIMEOUT) -> str:
    """GitLab URL-encoded 'group%2Frepo' (every '/' → '%2F', incl. subgroups)."""
    view = run(["glab", "repo", "view", "--output", "json"], timeout=timeout)
    path = json.loads(view)["path_with_namespace"]
    return urllib.parse.quote(path, safe="")


def gh_api(path: str, *, paginate: bool = False, jq: str | None = None) -> str:
    """Call `gh api <path>`; `paginate` follows Link headers, `jq` filters via `-q`."""
    argv = ["gh", "api"]
    if paginate:
        argv.append("--paginate")
    argv.append(path)
    if jq:
        argv += ["-q", jq]
    return run(argv)


def glab_api(path: str, *, paginate: bool = False, jq: str | None = None) -> str:
    """Call `glab api <path>`; `paginate` follows all pages, `jq` filters via `-q`."""
    argv = ["glab", "api"]
    if paginate:
        argv.append("--paginate")
    argv.append(path)
    if jq:
        argv += ["-q", jq]
    return run(argv)
