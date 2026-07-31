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
import time
import urllib.parse

DEFAULT_TIMEOUT = 30

_SSH_RE = re.compile(r"^[^@]+@([^:]+):")


def run(argv: list[str], *, timeout: int = DEFAULT_TIMEOUT, check: bool = True) -> str:
    """Run a CLI as an argv list; return stripped stdout. Never invokes a shell.

    Propagates subprocess.CalledProcessError / TimeoutExpired so callers that want a
    retry loop (flow-wait-ci) can catch, and callers that want a hard failure
    (flow-review-collect) can let it abort.
    """
    proc = subprocess.run(argv, capture_output=True, text=True, check=check, timeout=timeout)
    return proc.stdout.strip()


#: Read-path retry pauses, in seconds. Three attempts add at most ~5 s to an interactive wait.
_RETRY_PAUSES = (1, 4)
#: A rate limit does not clear in a second, so its pauses are an order of magnitude longer.
_RATE_LIMIT_PAUSES = (10, 30)

#: stderr signatures of failures that will not succeed on a retry. Matched case-insensitively
#: as substrings, because the CLIs expose no HTTP status — their stderr text is the only signal.
_PERMANENT_SIGNATURES = (
    "auth login",
    "401",
    "bad credentials",
    "404",
    "not found",
    "could not resolve to a",
    "doesn't exist",
)
_RATE_LIMIT_SIGNATURES = ("rate limit", "429")


class ApiUnavailableError(RuntimeError):
    """A platform API call could not be completed. `permanent` distinguishes "try again later"
    from "this will never work here" (bad auth, or a GraphQL schema without the field we ask
    for), so callers can say which one happened instead of printing one vague message."""

    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


def _stderr_of(exc: BaseException) -> str:
    raw = getattr(exc, "stderr", None) or ""
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def api_run(argv: list[str], *, timeout: int = DEFAULT_TIMEOUT, sleep=time.sleep) -> str:
    """Run a platform API READ with retries; raise `ApiUnavailableError` when it cannot be completed.

    **Reads only.** Every caller here is idempotent (listings, `user`, `repo view`, `pr view`,
    the resolution GraphQL query), which is the entire reason a retry is safe. Do NOT route a
    write through this: re-running a reply POST double-posts a comment on the platform, and the
    duplicate is not recoverable. Phase 5 replies deliberately go through a direct `gh api`
    from the skill, not through this module.

    `sleep` is injected so tests do not wait.
    """
    attempts = len(_RETRY_PAUSES) + 1
    for attempt in range(attempts):
        try:
            return run(argv, timeout=timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            stderr = _stderr_of(exc).lower()
            detail = f"{' '.join(argv)}: {_stderr_of(exc).strip() or exc}"
            if any(sig in stderr for sig in _PERMANENT_SIGNATURES):
                raise ApiUnavailableError(detail, permanent=True) from exc
            if attempt == attempts - 1:
                raise ApiUnavailableError(detail, permanent=False) from exc
            pauses = _RATE_LIMIT_PAUSES if any(sig in stderr for sig in _RATE_LIMIT_SIGNATURES) else _RETRY_PAUSES
            sleep(pauses[attempt])
    msg = "unreachable"  # pragma: no cover - the loop either returns or raises
    raise AssertionError(msg)


def host_from_remote(url: str) -> str | None:
    """Extract the host from an SSH or HTTPS git remote URL; None if unparseable.

    Any `scheme://` URL (https://, ssh://, git+ssh://) is parsed with urlparse — its netloc
    covers ssh:// remotes that the scp-form regex misses. The scp form `git@host:path` (no
    scheme) stays on the regex. Any `user@` in the netloc is stripped; the port is kept as-is
    (host:port normalization is a separate follow-up).
    """
    if "://" in url:
        return urllib.parse.urlparse(url).netloc.rsplit("@", 1)[-1] or None
    m = _SSH_RE.match(url)  # scp-like git@host:path
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


def gh_api(path: str, *, paginate: bool = False, jq: str | None = None, slurp: bool = False) -> str:
    """Call `gh api <path>`; `paginate` follows Link headers, `jq` filters via `-q`.

    `slurp` adds `--slurp`, which wraps each page into one outer JSON array instead of
    emitting each page as its own back-to-back top-level document (the latter breaks a
    bare `json.loads` on any multi-page response with "Extra data"). `--slurp` and `-q`
    are mutually exclusive in `gh api` itself, so `slurp=True, jq=...` raises here.
    """
    if slurp and jq:
        msg = "gh_api: slurp and jq are mutually exclusive"
        raise ValueError(msg)
    argv = ["gh", "api"]
    if paginate:
        argv.append("--paginate")
    if slurp:
        argv.append("--slurp")
    argv.append(path)
    if jq:
        argv += ["-q", jq]
    return api_run(argv)


def glab_api(path: str, *, paginate: bool = False) -> str:
    """Call `glab api <path>`; `paginate` follows all pages.

    Unlike `gh api`, `glab api` has **no** `-q`/`--jq` filter flag — it expects the caller to
    pipe the raw JSON to an external `jq`. So this wrapper never adds one; callers parse the
    returned JSON in Python (e.g. `json.loads(glab_api("user"))["username"]`).
    """
    argv = ["glab", "api"]
    if paginate:
        argv.append("--paginate")
    argv.append(path)
    return api_run(argv)
