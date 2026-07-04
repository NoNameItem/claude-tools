"""Smoke tests for wait_for_checks.py (run manually, not in CI)."""

# INP001: test dir is an implicit namespace package (no __init__.py, matching
# plugins/flow/bin/tests/); the suppression is intentional, not an oversight.
# ruff: noqa: INP001

from conftest import check_runs, commit_status, run_helper

SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

# A fully-settled pipeline: both anchors terminal + a CI check completed.
TERMINAL_RUNS = check_runs(
    ("claude-review", "completed", "success"),
    ("Python CI", "completed", "success"),
)
TERMINAL_STATUS = commit_status("success", ("review-gate", "success"))


def _seed_terminal(fake, sha=SHA):
    fake.write(sha, "check-runs", "terminal", TERMINAL_RUNS)
    fake.write(sha, "status", "terminal", TERMINAL_STATUS)


def test_succeeds_and_emits_conclusions(fake_gh):
    _seed_terminal(fake_gh)
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    # one line per check-run and per status, with conclusions/states
    assert "claude-review success" in r.stdout
    assert "Python CI success" in r.stdout
    assert "review-gate success" in r.stdout


def test_blocks_while_a_check_is_in_progress(fake_gh):
    # Anchors terminal, but a CI check is still running -> not terminal -> timeout(2).
    fake_gh.write(
        SHA,
        "check-runs",
        "pending",
        check_runs(
            ("claude-review", "completed", "success"),
            ("Python CI", "in_progress", None),
        ),
    )
    # combined status is success (check-runs don't drive the combined commit-status),
    # so exit-2 comes solely from the "a check-run is still in_progress" rule.
    fake_gh.write(SHA, "status", "pending", commit_status("success", ("review-gate", "success")))
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 2, r.stdout


def test_blocks_until_anchor_check_run_present(fake_gh):
    # Everything terminal EXCEPT claude-review is absent -> must not conclude -> timeout(2).
    fake_gh.write(
        SHA,
        "check-runs",
        "pending",
        check_runs(("Python CI", "completed", "success")),
    )
    fake_gh.write(SHA, "status", "pending", commit_status("success", ("review-gate", "success")))
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 2, r.stdout


def test_blocks_until_review_gate_status_present(fake_gh):
    # review-gate status absent (combined success, all check-runs done) -> anchor 2
    # missing -> must not conclude -> timeout(2). combined != "pending" so the block
    # comes solely from the review-gate anchor, not the catch-all.
    fake_gh.write(SHA, "check-runs", "pending", TERMINAL_RUNS)
    fake_gh.write(SHA, "status", "pending", commit_status("success", ("other-ci", "success")))
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 2, r.stdout


def test_keys_on_the_passed_sha(fake_gh):
    # OLD sha fully green; NEW sha pending. Asking for NEW must NOT read OLD's green.
    old, new = SHA, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _seed_terminal(fake_gh, old)
    fake_gh.write(new, "check-runs", "pending", check_runs(("Python CI", "in_progress", None)))
    fake_gh.write(new, "status", "pending", commit_status("pending", ("review-gate", "pending")))
    assert run_helper("42", new, env=fake_gh.env()).returncode == 2
    assert run_helper("42", old, env=fake_gh.env()).returncode == 0


def test_loops_until_terminal_then_succeeds(fake_gh):
    # First poll pending, second terminal -> exit 0 (proves it loops, not one-shot).
    fake_gh.set_flip_after(1)
    fake_gh.write(SHA, "check-runs", "pending", check_runs(("claude-review", "in_progress", None)))
    fake_gh.write(SHA, "status", "pending", commit_status("pending", ("review-gate", "pending")))
    _seed_terminal(fake_gh)
    env = {**fake_gh.env(), "WAIT_TIMEOUT": "30", "WAIT_INTERVAL": "0"}
    r = run_helper("42", SHA, env=env)
    assert r.returncode == 0, r.stderr


def test_blocks_when_a_nonanchor_status_is_pending(fake_gh):
    # Both anchors terminal and all check-runs completed, but a third (non-anchor)
    # status is still pending -> combined "pending" -> catch-all blocks -> exit 2.
    fake_gh.write(SHA, "check-runs", "pending", TERMINAL_RUNS)
    fake_gh.write(
        SHA,
        "status",
        "pending",
        commit_status("pending", ("review-gate", "success"), ("extra-ci", "pending")),
    )
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 2, r.stdout


def test_blocks_when_check_runs_view_is_truncated(fake_gh):
    # total_count exceeds the returned runs (page truncated) -> incomplete view ->
    # must not conclude even though the visible checks look done -> exit 2.
    fake_gh.write(
        SHA,
        "check-runs",
        "pending",
        check_runs(("claude-review", "completed", "success"), total_count=5),
    )
    fake_gh.write(SHA, "status", "pending", commit_status("success", ("review-gate", "success")))
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 2, r.stdout


def test_usage_error_exits_1(fake_gh):
    # Wrong argc is a caller bug, not a timeout -> exit 1 (distinct from 2).
    assert run_helper("only-one-arg", env=fake_gh.env()).returncode == 1


def test_paginates_check_runs_beyond_one_page(fake_gh):
    # total_count (3) exceeds page 1 (2 runs); page 2 supplies the third. The helper
    # must merge all pages before the completeness check, or a >100-run head would
    # look permanently truncated and time out. Merged view is complete -> terminal.
    two_pages = (
        '[{"check_runs":['
        '{"name":"claude-review","status":"completed","conclusion":"success"},'
        '{"name":"CI-a","status":"completed","conclusion":"success"}],"total_count":3},'
        '{"check_runs":['
        '{"name":"CI-b","status":"completed","conclusion":"success"}],"total_count":3}]'
    )
    fake_gh.write(SHA, "check-runs", "terminal", two_pages)
    fake_gh.write(SHA, "status", "terminal", TERMINAL_STATUS)
    r = run_helper("42", SHA, env=fake_gh.env())
    assert r.returncode == 0, r.stderr
    assert "CI-b success" in r.stdout  # a page-2 run made it into the merged/emitted set
