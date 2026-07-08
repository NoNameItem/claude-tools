"""Tests for flow-wait-ci (GitHub + GitLab backends of the review-loop wait)."""

# ruff: noqa: INP001

from conftest import SHA, gh_response, gl_jobs, gl_mr, run_helper


def _gh(*args, env):
    return run_helper("flow-wait-ci", *args, env=env)


# --- usage --------------------------------------------------------------------


def test_usage_missing_platform_exits_1(fake_gh):
    r = _gh("42", SHA, env=fake_gh.env())
    assert r.returncode == 1, r.stderr


def test_usage_bad_platform_exits_1(fake_gh):
    r = _gh("42", SHA, "--platform", "bitbucket", env=fake_gh.env())
    assert r.returncode == 1, r.stderr


def test_usage_missing_sha_exits_1(fake_gh):
    r = _gh("42", "--platform", "github", env=fake_gh.env())
    assert r.returncode == 1, r.stderr


# --- github backend -----------------------------------------------------------


def test_github_terminal_emits_check_lines(fake_gh):
    # A settled pipeline: one check-run + one status context, both terminal. The queue
    # repeats the single response, so poll-1 records the signature and poll-2 matches it
    # (stability window) -> exit 0, emitting one line per node for the skill to classify.
    fake_gh.queue(
        [
            gh_response(
                nodes=[
                    ("check", "CI", "COMPLETED", "SUCCESS"),
                    ("status", "gate", "SUCCESS"),
                ]
            )
        ]
    )
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    assert "CI SUCCESS" in r.stdout
    assert "gate SUCCESS" in r.stdout


def test_github_timeout_exits_2(fake_gh):
    # Rollup present but a check is IN_PROGRESS (active) -> never terminal. WAIT_TIMEOUT=0
    # -> after the first non-terminal poll the deadline is past -> exit 2 (the caller asks).
    fake_gh.queue([gh_response(nodes=[("check", "CI", "IN_PROGRESS", None)])])
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env(WAIT_TIMEOUT="0"))
    assert r.returncode == 2, r.stdout


def test_github_no_ci_exits_4(fake_gh):
    # Null rollup (no checks registered) + grace elapsed (WAIT_GRACE=0) -> exit 4. This is
    # the generalization beyond claude-tools: an arbitrary PR may have no CI/bots at all.
    fake_gh.queue([gh_response(rollup=False)])
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env(WAIT_GRACE="0"))
    assert r.returncode == 4, r.stdout


def test_github_head_moved_exits_3(fake_gh):
    # The pipeline for SHA is terminal, but the PR head advanced during the wait
    # (headRefOid != SHA) -> exit 3 so the caller re-captures HEAD and re-waits.
    fake_gh.queue(
        [
            gh_response(
                nodes=[("check", "CI", "COMPLETED", "SUCCESS")],
                head="cccccccccccccccccccccccccccccccccccccccc",
            )
        ]
    )
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env())
    assert r.returncode == 3, r.stdout


def test_github_waits_for_count_stability(fake_gh):
    # poll-1 sees 1 check; poll-2 sees 2 (a second check registered late) -> signatures
    # differ, no conclusion; poll-3 matches poll-2 -> terminal. Proves the stability window
    # covers a late-registering check that a one-shot view would miss.
    one = gh_response(nodes=[("check", "CI", "COMPLETED", "SUCCESS")])
    two = gh_response(
        nodes=[
            ("check", "CI", "COMPLETED", "SUCCESS"),
            ("check", "CI2", "COMPLETED", "SUCCESS"),
        ]
    )
    fake_gh.queue([one, two, two])
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    assert "CI2 SUCCESS" in r.stdout


def test_github_unknown_merge_state_blocks(fake_gh):
    # Everything terminal EXCEPT mergeStateStatus==UNKNOWN for the first 3 polls; the 4th is
    # CLEAN. Counts are identical throughout, so without the UNKNOWN guard the helper would
    # conclude on poll-2 (stable counts). Requiring >= 4 polls proves UNKNOWN kept it waiting.
    unk = gh_response(nodes=[("check", "CI", "COMPLETED", "SUCCESS")], merge="UNKNOWN")
    clean = gh_response(nodes=[("check", "CI", "COMPLETED", "SUCCESS")], merge="CLEAN")
    fake_gh.queue([unk, unk, unk, clean])
    r = _gh("42", SHA, "--platform", "github", env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    assert fake_gh.poll_count() >= 4, f"concluded too early ({fake_gh.poll_count()} polls)"


def test_github_survives_transient_poll_failure(fake_gh):
    # A garbage/non-JSON poll -> _gh_poll returns None -> the loop retries rather than
    # crashing; the next (terminal) poll converges. Proves transient-failure resilience.
    fake_gh.queue(["not valid json", gh_response(nodes=[("check", "CI", "COMPLETED", "SUCCESS")])])
    r = run_helper("flow-wait-ci", "42", SHA, "--platform", "github", env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    assert "CI SUCCESS" in r.stdout


# --- gitlab backend -----------------------------------------------------------


def _gl(*args, env):
    return run_helper("flow-wait-ci", *args, env=env)


def test_gitlab_terminal_success(fake_glab):
    fake_glab.queue([gl_mr(status="success")])
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env())
    assert r.returncode == 0, r.stderr
    assert "pipeline success" in r.stdout


def test_gitlab_waits_while_running(fake_glab):
    # poll-1 running (active) -> wait; poll-2 success -> terminal. No stability window
    # needed: the head pipeline is a single authoritative status.
    fake_glab.queue([gl_mr(status="running"), gl_mr(status="success")])
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env())
    assert r.returncode == 0, r.stderr


def test_gitlab_no_pipeline_exits_4(fake_glab):
    # workflow:rules may never create a pipeline -> grace elapses -> exit 4.
    fake_glab.queue([gl_mr(present=False)])
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env(WAIT_GRACE="0"))
    assert r.returncode == 4, r.stdout


def test_gitlab_manual_is_terminal(fake_glab):
    # A blocking `manual` pipeline never reaches success; waiting forever is wrong ->
    # terminal-for-waiting. The skill treats `pipeline manual` as green (does not trip
    # the red-gate), so exit 0.
    fake_glab.queue([gl_mr(status="manual")])
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env())
    assert r.returncode == 0, r.stderr
    assert "pipeline manual" in r.stdout


def test_gitlab_failed_emits_failed_jobs(fake_glab):
    # A red pipeline: emit `pipeline failed` + one line per failed job with allow_failure
    # false. allow_failure jobs are excluded (they don't block).
    fake_glab.queue([gl_mr(status="failed", pid=7)])
    fake_glab.set_jobs(gl_jobs(("lint", False), ("flaky", True)))
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env())
    assert r.returncode == 0, r.stderr
    assert "pipeline failed" in r.stdout
    assert "lint failed" in r.stdout
    assert "flaky failed" not in r.stdout


def test_gitlab_head_moved_exits_3(fake_glab):
    # The pipeline for SHA finished, but the MR diff head advanced (mr.sha != SHA) -> exit 3.
    fake_glab.queue(
        [
            gl_mr(
                status="success",
                head="dddddddddddddddddddddddddddddddddddddddd",
                pipeline_sha=SHA,
            )
        ]
    )
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env())
    assert r.returncode == 3, r.stdout


def test_gitlab_ignores_pipeline_for_other_sha(fake_glab):
    # head_pipeline exists but is for a different sha (a stale pipeline object). Treated as
    # "no pipeline for this head yet" -> waits, then exit 4 once grace elapses.
    fake_glab.queue([gl_mr(status="success", head=SHA, pipeline_sha="0000000000000000000000000000000000000000")])
    r = _gl("42", SHA, "--platform", "gitlab", env=fake_glab.env(WAIT_GRACE="0"))
    assert r.returncode == 4, r.stdout
