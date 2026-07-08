"""Tests for flow-wait-ci (GitHub + GitLab backends of the review-loop wait)."""

# ruff: noqa: INP001

from conftest import SHA, gh_response, run_helper


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
