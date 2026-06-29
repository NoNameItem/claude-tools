# PR Review Merge Gate (Codex + Claude) — Design

**Date:** 2026-06-26 (updated 2026-06-29 with empirical Codex findings)
**Status:** Workflow implemented (`review-gate.yml`); ruleset pending PR #86 merge.
**Scope:** repo (`.github/`, repository ruleset)
**Depends on:** PR #86 (`add-claude-github-actions`) — adds `claude-code-review.yml`, whose
native `claude-review` check the ruleset requires.

---

## 1. Problem & Context

We are moving off CodeRabbit as primary reviewer (its free OSS-tier rate limit can't keep
up with our push frequency). The replacement reviewer set:

- **Claude Code Review** — `anthropics/claude-code-action@v1` in `claude-code-review.yml`
  (added in PR #86). Runs as a GitHub Actions job → emits a native check run.
- **Codex** — the OpenAI GitHub app (`chatgpt-codex-connector[bot]`). Advisory; signals via
  reactions/reviews, **no check run or commit status**.

Gap: nothing prevents merging a PR before these automated reviews have run on the latest
commit. This design adds that gate.

**Non-goal:** blocking on review *findings*. That is handled by GitHub's native
**"Require conversation resolution before merging"** — unresolved reviewer threads block the
merge. This gate is about **completion** ("both reviewers have reviewed the head commit").

## 2. Decisions

| Decision | Choice |
|---|---|
| Gate semantics | **Completion-gate** (review ran for head SHA), not quality-gate |
| Claude enforcement | **Native required check** `claude-review` (re-runs per push → carries SHA-strictness for Claude) |
| Codex enforcement | **Synthetic `review-gate` workflow** — Codex is an app with no requireable check |
| Gated reviewers | **Codex AND Claude** |
| Codex detection | review with `commit_id == head` (findings) **OR** a 👍 reaction newer than the head commit (clean) |
| Re-arm on push | **Automatic** — Codex strips its 👍 on each push; a fresh-timestamp 👍 / review@head is required again |
| Clean-case re-trigger | **In-job poll** (a 👍 reaction fires no workflow event) |

## 3. Empirical facts — Codex signal model (verified 2026-06-29)

Codex exposes review state through **reactions and reviews on the PR**, not checks/statuses.
Verified live (PRs #86–#88, incl. two deliberate experiments):

| Codex state | Signal |
|---|---|
| Reviewing (just pushed) | 👀 (`eyes`) reaction; any prior 👍 removed |
| Clean (no findings) | 👍 (`+1`) reaction, **re-added with a fresh `created_at`** after each re-review |
| Has findings | a PR **review** with `commit_id == head` + inline comments; **no** 👍 |

Key consequences:
- **No check run / commit status from Codex** → can't require it natively; a synthetic check
  is necessary.
- The 👍 reaction is **not tied to a commit SHA**, but Codex **deletes and re-adds** it with a
  new timestamp on each clean re-review (exp1: `08:34:41Z → 09:07:30Z` after a clean push).
  So "👍 newer than the head commit" is a reliable proxy for "clean review of the head."
- On a bad commit Codex **removes the 👍** and posts a review pinned to the head SHA (exp2:
  👍 gone, `COMMENTED @ <head>` + 4 inline comments).
- Re-arm is therefore automatic: a new push strips the 👍 → gate must wait for a fresh
  signal.

Codex docs ([integrations/github](https://developers.openai.com/codex/integrations/github),
[use-cases](https://developers.openai.com/codex/use-cases/github-code-reviews)) document the
`@codex review` comment trigger and automatic-on-open review; on-push re-review and the
reaction model above are undocumented but empirically confirmed here.

Known Claude-action footguns (only relevant because the native `claude-review` check must go
green): exit 5 after success ([#846](https://github.com/anthropics/claude-code-action/issues/846)),
exit 1 ([#911](https://github.com/anthropics/claude-code-action/issues/911)), self-commit
loop ([#1299](https://github.com/anthropics/claude-code-action/issues/1299)). Handled
reactively (§7 Phase 3), not by this gate.

## 4. Architecture

### 4.1 Claude — native required check (no code)

`claude-code-review.yml` job `claude-review` already produces a check run per commit; it
triggers on `pull_request: synchronize`, so it re-runs and re-arms per push. We just add
**`claude-review`** to the ruleset's required checks (and pin the job name so the reference
is stable).

### 4.2 Codex — synthetic `review-gate.yml`

Single job whose check-run name is **`review-gate`** (that name is what the ruleset requires).

**Triggers:**

```yaml
on:
  pull_request:        { types: [opened, synchronize, reopened] }
  pull_request_review: { types: [submitted] }
```

- `pull_request: synchronize` — new head → job runs → polls (re-arm).
- `pull_request_review: submitted` — fires when Codex posts a *findings* review (or a human
  reviews) → fast re-evaluation.
- No `check_run` trigger needed (the gate no longer observes Claude).

**Detection (`codex_done(head)`):**

```
codex_done = (∃ Codex review with commit_id == HEAD_SHA)            # findings on head
          OR (∃ Codex 👍 reaction with created_at > head commit time)  # clean review of head
```

**Why the timestamp comparison (the lingering-👍 race):** right after a push the *previous*
commit's 👍 may still be present for a few seconds/minutes before Codex strips it. A bare
"👍 exists" check would falsely open the gate. Comparing the 👍 `created_at` against the head
commit's committer date rejects the stale 👍 and accepts only the fresh one Codex re-adds
after reviewing the new head. (Assumes committer clock ≈ GitHub time — true for NTP hosts;
see §9.)

**Clean-case re-trigger — in-job poll:** a 👍 reaction fires no workflow event, so the job
**polls** (every 30 s, up to ~12 min — observed Codex latency is ~5–8 min). While polling the
`review-gate` check is pending (merge blocked); it goes green when Codex settles. On timeout
it fails with a message to re-run once Codex finishes. The findings path also resolves
immediately via the `pull_request_review` trigger.

**Guards / config:** fork guard (`head.repo.full_name == github.repository`),
`permissions: { contents: read, pull-requests: read }`, `concurrency` keyed on the PR with
`cancel-in-progress` (a new push cancels a stale poll).

## 5. Repository Settings (ruleset on `master`)

- **Require status checks to pass before merging** → **`claude-review`** + **`review-gate`**.
- **Require conversation resolution before merging** ✅ (the quality half).
- *(optional)* **Require branches to be up to date before merging**.

> Requires PR #86 merged first, so `claude-review` runs on PRs against `master`.

## 6. Edge Cases & Mitigations

| Case | Behavior |
|---|---|
| First run on a fresh push | `review-gate` pending (polling) until Codex settles — correct. |
| New push after a clean review | Codex strips 👍 → poll waits for a fresh 👍 / review@head → re-arm. |
| Stale 👍 right after push | Rejected by the `created_at > head commit time` check. |
| Findings | Codex posts review@head → gate "reviewed"; the open threads block via conversation resolution. |
| Codex slower than the poll timeout | `review-gate` fails red; re-run the check once Codex finishes. |
| Fork PRs | Job skipped by the fork guard (skipped check is treated as satisfied); forks are out of scope. |
| Claude check flake (#846/#911/#1299) | Re-run the job; if chronic, harden the workflow (§7 Phase 3). |

## 7. Implementation Phases

**Phase 1 — Empirical re-arm test. ✅ DONE.** Confirmed Codex re-reviews on push and the
reaction state machine (§3). Outcome: re-arm is automatic; no `@codex review` auto-comment or
PAT needed; clean case handled by the timestamp check + in-job poll.

**Phase 2 — `review-gate.yml` + ruleset.**
- `review-gate.yml` — **done** (this branch). Validated with `actionlint` (+ shellcheck on the
  `run` block).
- Ruleset — require `claude-review` + `review-gate` + conversation resolution. **Pending PR
  #86 merge** (so `claude-review` exists on `master`).

**Phase 3 — (optional, reactive) Harden Claude check.** Only if `claude-review` proves flaky:
normalize its exit code on a posted review and skip-with-pass on bot-authored commits
(#1299). Separate task; not required for the gate to function.

## 8. Testing

- **Static:** `actionlint` (runs shellcheck on the `run:` block) — passing.
- **Live:** on a test PR — open → `review-gate` pending → Codex 👍/review → green → push again
  → pending → re-review → green; and a findings push → review@head → green-but-threads-block.
  (The Codex behavior underpinning this was verified during Phase 1/exp2.)

## 9. Open Questions / Caveats

1. **Clock skew** — the clean-case check compares the 👍 `created_at` to the head commit's
   committer date. A badly-skewed committer clock could mis-time it; negligible on NTP hosts.
   If it ever bites, add a small grace margin or switch to observing the 👀→👍 transition.
2. **Ruleset sequencing** — must land PR #86 first (so `claude-review` is on `master`).
3. **Claude check reliability** — leave native unless it flakes chronically (then Phase 3).

## 10. Out of Scope

- Quality-gate / fail-on-findings (handled by conversation resolution).
- Reviewing fork PRs.
- Retiring CodeRabbit configuration (separate cleanup).
