"""Tests for flow-codex-agent-setup / _codex_agents.py (optional Codex profile setup).

Security-sensitive helper: it must never leak or read unrelated `.codex` state (notably
`.codex/config.toml`, which can hold machine-local credentials), never overwrite an existing
file, never follow a symlink out of the project root, and must treat any ambiguous identity
as a global reason to create nothing (uniqueness of the three required names cannot be
proven). These tests exercise real filesystem behavior (real tmp dirs, real subprocesses,
real git worktrees) rather than mocking the classification logic.
"""

# ruff: noqa: INP001  # bin/tests/ intentionally has no __init__.py (pytest rootdir layout)

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BIN = Path(__file__).parent.parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import _codex_agents  # noqa: E402  (import after BIN is on sys.path — sibling-module pattern)
from _codex_agents import create_profiles, inspect_project  # noqa: E402

# NOTE: `run_setup`/`_run_helper` below inline a minimal subprocess-based helper rather than
# importing `conftest.run_helper`, keeping this module self-contained.


def _run_helper(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a bin/ helper via the current interpreter; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(BIN / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# --- shared test helpers -----------------------------------------------------------------


def run_setup(command: str, project_root: Path, request_obj: dict[str, object] | None = None) -> dict[str, object]:
    """Run the CLI end-to-end via subprocess; return the parsed JSON stdout.

    The request JSON is written to a throwaway temp file OUTSIDE `project_root` (mirroring
    the skill's own "write outside `.codex/`" rule) so a test project always starts from
    exactly the files the test itself created.
    """
    args = [command, "--project-root", str(project_root)]
    request_path = None
    if request_obj is not None:
        fd, request_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as stream:
            json.dump(request_obj, stream)
        args += ["--request-json", request_path]
    try:
        result = _run_helper("flow-codex-agent-setup", *args)
        assert result.stdout, f"no stdout; stderr was: {result.stderr}"
        return json.loads(result.stdout)
    finally:
        if request_path is not None:
            Path(request_path).unlink(missing_ok=True)


def request(*profiles: tuple[str, str, str]) -> dict[str, object]:
    return {"profiles": [{"tier": tier, "model": model, "reasoning": reasoning} for tier, model, reasoning in profiles]}


def make_request_for_all_profiles() -> dict[str, object]:
    return request(
        ("fast", "account-fast", "low"),
        ("balanced", "account-balanced", "medium"),
        ("strongest", "account-strong", "high"),
    )


def compatible_profile(name: str, model: str, reasoning: str) -> str:
    """Render a fully Flow-compatible profile for whichever tier owns `name`."""
    tier = next(t for t, n in _codex_agents.PROFILE_NAMES.items() if n == name)
    return _codex_agents.render_profile(tier, model, reasoning)


def profile_data(tier: str) -> dict[str, object]:
    """A baseline Flow-compatible field set for `tier`, for mutation in contract tests."""
    return {
        "name": _codex_agents.PROFILE_NAMES[tier],
        "description": _codex_agents.DESCRIPTIONS[tier],
        "model": "account-model",
        "model_reasoning_effort": "low",
        "developer_instructions": _codex_agents.DEVELOPER_INSTRUCTIONS,
    }


def write_profile(project_root: Path, filename: str, data: dict[str, object]) -> Path:
    agents = project_root / ".codex" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{key} = {json.dumps(value)}\n" for key, value in data.items())
    path = agents / filename
    path.write_text(text)
    return path


def make_symlink_component(tmp_path: Path, link_name: str, target: Path) -> None:
    link = tmp_path / link_name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


# --- Step 2 tests (verbatim from the task brief) ------------------------------------------


def test_empty_project_previews_three_profiles(tmp_path: Path) -> None:
    result = run_setup(
        "preview",
        tmp_path,
        request(
            ("fast", "account-fast", "low"),
            ("balanced", "account-balanced", "medium"),
            ("strongest", "account-strong", "high"),
        ),
    )
    assert [item["name"] for item in result["missing"]] == [
        "flow-fast",
        "flow-balanced",
        "flow-strongest",
    ]
    assert not (tmp_path / ".codex").exists()


def test_profile_identity_comes_from_toml_name(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "unexpected.toml").write_text(compatible_profile("flow-fast", "custom", "xhigh"))
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "compatible"


def test_create_never_overwrites_a_concurrent_file(tmp_path: Path) -> None:
    plan = make_request_for_all_profiles()
    run_setup("preview", tmp_path, plan)
    target = tmp_path / ".codex" / "agents" / "flow-fast.toml"
    target.parent.mkdir(parents=True)
    target.write_text('name = "someone-else"\n')
    result = run_setup("create", tmp_path, plan)
    assert target.read_text() == 'name = "someone-else"\n'
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert {item["name"] for item in result["created"]} == {
        "flow-balanced",
        "flow-strongest",
    }


@pytest.mark.parametrize("link_name", [".codex", ".codex/agents", ".codex/agents/flow-fast.toml"])
def test_symlinked_target_is_rejected(tmp_path: Path, link_name: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    make_symlink_component(tmp_path, link_name, outside)
    result = run_setup("create", tmp_path, make_request_for_all_profiles())
    assert result["created"] == []
    assert "symlink" in json.dumps(result["conflicts"]).lower()


def test_duplicate_internal_name_conflicts_only_that_profile(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    text = compatible_profile("flow-fast", "custom", "low")
    (agents / "one.toml").write_text(text)
    (agents / "two.toml").write_text(text)
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert result["profiles"]["flow-balanced"]["status"] == "missing"


def test_required_filename_with_another_name_is_a_conflict(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "flow-fast.toml").write_text('name = "other-agent"\n')
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"


@pytest.mark.parametrize(
    ("model", "reasoning"),
    [
        ("", "low"),
        ("account-model", ""),
        ("account-model", "unsupported"),
    ],
)
def test_invalid_requested_values_are_rejected(
    tmp_path: Path,
    model: str,
    reasoning: str,
) -> None:
    result = run_setup("preview", tmp_path, request(("fast", model, reasoning)))
    assert result["missing"] == []
    assert result["profiles"]["flow-fast"]["status"] == "invalid"


def test_compatible_contract_allows_user_model_edits(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "flow-fast.toml").write_text(compatible_profile("flow-fast", "user-edited-model", "ultra"))
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "compatible"


@pytest.mark.parametrize(
    "mutation",
    [
        {"description": "different"},
        {"developer_instructions": "broaden the task"},
        {"sandbox_mode": "danger-full-access"},
    ],
)
def test_non_model_contract_changes_conflict(
    tmp_path: Path,
    mutation: dict[str, str],
) -> None:
    write_profile(tmp_path, "flow-fast.toml", profile_data("fast") | mutation)
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"


def test_ambiguous_malformed_toml_blocks_all_creation(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "broken.toml").write_text("name = [not valid TOML\n")
    result = run_setup("create", tmp_path, make_request_for_all_profiles())
    assert result["created"] == []
    assert result["global_conflicts"]


def test_malformed_toml_with_required_name_blocks_only_that_profile(tmp_path: Path) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    (agents / "broken.toml").write_text('name = "flow-fast"\nmodel = [broken\n')
    result = run_setup("inspect", tmp_path)
    assert result["profiles"]["flow-fast"]["status"] == "conflict"
    assert result["profiles"]["flow-balanced"]["status"] == "missing"


def test_inspection_never_reads_unrelated_codex_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('sonar_token = "do-not-read"\n')
    original = Path.read_text

    def guarded_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == config:
            msg = "must not read .codex/config.toml"
            raise AssertionError(msg)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    inspect_project(tmp_path)


def test_unreadable_agent_file_blocks_globally_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    unreadable = agents / "flow-fast.toml"
    unreadable.write_text('name = "flow-fast"\n')
    original = Path.read_text

    def failing_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == unreadable:
            msg = "permission denied"
            raise OSError(msg)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read)
    # Must not raise; an unreadable candidate becomes a global block, not a traceback.
    result = inspect_project(tmp_path)
    assert any("flow-fast.toml" in item for item in result["global_conflicts"])


def test_linked_worktree_warns_and_preserves_unrelated_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "linked"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Flow Test",
            "-c",
            "user.email=flow@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(source), "worktree", "add", "-q", str(worktree)], check=True)
    gitignore = worktree / ".gitignore"
    gitignore.write_text(".local-only\n")
    config = worktree / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('machine_token = "unchanged"\n')
    user_agent = tmp_path / "home" / ".codex" / "agents" / "personal.toml"
    user_agent.parent.mkdir(parents=True)
    user_agent.write_text('name = "personal"\n')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    before = {path: path.read_bytes() for path in (gitignore, config, worktree / ".git", user_agent)}

    result = create_profiles(worktree, make_request_for_all_profiles())

    assert result["linked_worktree"] is True
    assert all(path.read_bytes() == content for path, content in before.items())


# --- regression tests for the PR #113 review round (C6/C2/C7) ------------------------------


def _load_cli() -> object:
    """Load the extension-less CLI script as a module, to unit-test its helpers."""
    spec = importlib.util.spec_from_loader(
        "flow_codex_agent_setup_cli",
        importlib.machinery.SourceFileLoader("flow_codex_agent_setup_cli", str(BIN / "flow-codex-agent-setup")),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = _load_cli()


def run_setup_raw(
    command: str,
    project_root: Path,
    request_obj: dict[str, object] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """Like `run_setup`, but also returns the CompletedProcess so exit codes are assertable."""
    args = [command, "--project-root", str(project_root)]
    request_path = None
    if request_obj is not None:
        fd, request_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as stream:
            json.dump(request_obj, stream)
        args += ["--request-json", request_path]
    try:
        proc = _run_helper("flow-codex-agent-setup", *args)
        assert proc.stdout, f"no stdout; stderr was: {proc.stderr}"
        return proc, json.loads(proc.stdout)
    finally:
        if request_path is not None:
            Path(request_path).unlink(missing_ok=True)


@pytest.mark.parametrize("link_name", [".codex", ".codex/agents", ".codex/agents/flow-fast.toml"])
def test_dangling_symlink_component_is_rejected(tmp_path: Path, link_name: str) -> None:
    """A symlink whose target does not exist must still be rejected.

    Regression for the `current.exists() and current.is_symlink()` guard: `exists()` follows
    the link and is False for a dangling one, so the component slipped past entirely.
    """
    make_symlink_component(tmp_path, link_name, tmp_path / "no-such-target")
    proc, result = run_setup_raw("create", tmp_path, make_request_for_all_profiles())
    assert result["created"] == []
    assert "symlink" in json.dumps(result["conflicts"]).lower()
    assert proc.returncode == 1


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses write permissions")
def test_write_failure_is_reported_and_exits_nonzero(tmp_path: Path) -> None:
    """An OSError during the per-profile write must not exit 0.

    `create_profiles` records such a failure only in `failed` and leaves the profile status at
    "missing", so an exit-code check that looked only at statuses reported success.
    """
    agents = tmp_path / ".codex" / "agents"
    agents.mkdir(parents=True)
    agents.chmod(0o500)  # readable and traversable, not writable
    try:
        proc, result = run_setup_raw("create", tmp_path, make_request_for_all_profiles())
    finally:
        agents.chmod(0o700)
    assert result["created"] == []
    assert result["failed"], "an unwritable agents dir must populate `failed`"
    assert proc.returncode == 1


def test_codex_as_regular_file_yields_json_not_traceback(tmp_path: Path) -> None:
    """`.codex` existing as a plain file is recoverable project state, not a crash.

    `mkdir` raises NotADirectoryError there; it used to escape the result-building path, so the
    CLI printed a traceback and no JSON, violating its stdout contract.
    """
    (tmp_path / ".codex").write_text("not a directory\n")
    proc, result = run_setup_raw("create", tmp_path, make_request_for_all_profiles())
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert result["created"] == []
    assert any(item.get("name") is None for item in result["conflicts"])


def test_has_failure_flags_recorded_write_failures() -> None:
    """A populated `failed` list alone is enough to fail the exit code."""
    result = {"profiles": {"flow-fast": {"status": "missing"}}, "failed": [{"name": "flow-fast", "reason": "ENOSPC"}]}
    assert CLI._has_failure(result, {"flow-fast"}) is True


def test_has_failure_flags_nameless_conflict_regardless_of_wording() -> None:
    """A conflict with no `name` blocked the whole run, whatever its `reason` says."""
    escaped = {"conflicts": [{"reason": "target escapes project root: /x"}], "profiles": {}}
    denied = {"conflicts": [{"reason": "[Errno 13] Permission denied: '/x/.codex'"}], "profiles": {}}
    assert CLI._has_failure(escaped, set()) is True
    assert CLI._has_failure(denied, set()) is True


def test_has_failure_ignores_conflicts_scoped_to_other_tiers() -> None:
    """A named conflict is scoped to that profile and must not fail an unrelated request."""
    result = {
        "conflicts": [{"name": "flow-strongest", "reason": "flow-strongest.toml does not match the contract"}],
        "profiles": {"flow-fast": {"status": "missing"}, "flow-strongest": {"status": "conflict"}},
    }
    assert CLI._has_failure(result, {"flow-fast"}) is False


@pytest.mark.parametrize(("command", "has_write_keys"), [("inspect", False), ("preview", False), ("create", True)])
def test_error_result_matches_the_command_shape(tmp_path: Path, command: str, has_write_keys: bool) -> None:
    """`created`/`failed` exist only on `create`, so a failure mirrors that command's shape."""
    result = CLI._error_result(tmp_path, OSError("boom"), command)
    assert ("created" in result) is has_write_keys
    assert ("failed" in result) is has_write_keys
    assert result["global_conflicts"] == ["boom"]
    assert result["conflicts"] == [{"reason": "boom"}]


def test_write_failure_removes_the_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write that fails after `O_EXCL` created the file must not leave the target behind.

    A truncated profile is worse than none: the next run cannot parse it, `malformed_identity`
    cannot recover a unique name, and the whole create is blocked as an ambiguous identity.
    """
    original_fdopen = os.fdopen

    class FailingStream:
        def __init__(self, stream: object) -> None:
            self._stream = stream

        def __enter__(self) -> FailingStream:
            return self

        def __exit__(self, *exc_info: object) -> bool:
            self._stream.close()
            return False

        def write(self, _: str) -> int:
            msg = "[Errno 28] No space left on device"
            raise OSError(msg)

    def failing_fdopen(fd: int, *args: object, **kwargs: object) -> FailingStream:
        return FailingStream(original_fdopen(fd, *args, **kwargs))

    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    result = create_profiles(tmp_path, make_request_for_all_profiles())

    assert result["created"] == []
    assert len(result["failed"]) == 3
    assert list((tmp_path / ".codex" / "agents").glob("*.toml")) == [], "partial files must be cleaned up"


def test_pre_creation_failure_never_deletes_an_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An OSError raised BEFORE `O_EXCL` ran must not trigger the partial-file cleanup.

    `reject_symlink_components` runs inside the same `try` and can itself raise OSError
    (`resolve(strict=True)` on a vanished root, `is_symlink()` on EACCES/ESTALE). `os.open`
    never ran then, so the target may hold a complete file written by someone else -- the
    cleanup is gated on having created it, and this pins that.
    """
    agents = tmp_path / ".codex" / "agents"
    original = _codex_agents.reject_symlink_components
    concurrent_text = 'name = "flow-fast"\n# written by a concurrent writer\n'

    def racing_check(project_root: Path, target: Path) -> None:
        original(project_root, target)
        if target.name == "flow-fast.toml":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(concurrent_text)
            msg = "[Errno 116] Stale file handle"
            raise OSError(msg)

    monkeypatch.setattr(_codex_agents, "reject_symlink_components", racing_check)
    result = create_profiles(tmp_path, make_request_for_all_profiles())

    assert (agents / "flow-fast.toml").read_text() == concurrent_text, "must not delete a file we did not create"
    assert any(item["name"] == "flow-fast" for item in result["failed"])
