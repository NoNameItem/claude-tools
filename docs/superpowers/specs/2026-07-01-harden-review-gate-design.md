# Harden review-gate: freshness cutoff, base-change, self-modification — Design

**Date:** 2026-07-01 (revised 2026-07-03 after Codex review on PR #96 — see §8)
**Status:** Implemented on PR #96; revised per Codex round-5 review (§8).
**Scope:** repo (`.github/workflows/review-gate.yml`, `.github/scripts/`)
**Task:** claude-tools-cna (epic claude-tools-5vg, Repo-level tasks)
**Supersedes:** the freshness-cutoff caveat in
`2026-06-26-pr-review-merge-gate-design.md` §9.1, which assumed
`pull_request.updated_at` always reflects the head's push time. It does not for
`reopened` / `ready_for_review`.
**Source:** Codex round-4 review on PR #89 (comments 3504971741, 3504971749, 3504971756).
All three findings are valid but edge-case; the gate works for the normal
push → review → merge flow.

---

## 1. Problem & Context

`review-gate.yml` blocks merge until Codex has reviewed the head commit of a PR. It polls
(up to ~12 min) for one of two signals from `chatgpt-codex-connector[bot]`:

- **findings path** — a PR review with `commit_id == HEAD_SHA`;
- **clean path** — a `+1` (👍) reaction with `created_at` newer than a *freshness cutoff*.

The cutoff is `PUSHED_AT = github.event.pull_request.updated_at`. Codex round-4 review found
three defects in this model:

1. **Wrong freshness cutoff on non-push events.** `updated_at` equals the head's push time
   only for `synchronize` (and `opened`). On `reopened` / `ready_for_review` (no new push),
   `updated_at` is bumped to the *event* time, so a still-valid earlier 👍 looks stale → the
   clean path never passes → the 12-min poll times out → **false merge block on
   already-reviewed code.** *(Bites today.)*
2. **Base-branch change not covered.** Changing a PR's base changes the diff Codex should
   review while `HEAD_SHA` is unchanged. A previously-green gate survives even though Codex
   only reviewed the old base/diff. GitHub sends `pull_request: edited` with `changes.base`,
   which the gate does not listen to; and the findings path has *no* freshness check, so an
   old review pinned to `HEAD_SHA` still satisfies the gate.
3. **Self-modifying gate (security).** For a same-repo PR that edits `review-gate.yml`, the
   `pull_request` event runs the **PR's** version of the workflow — it could replace the poll
   with `exit 0` and self-approve. The job only reads PR metadata (no checkout/exec of head
   code), so it is safe to run the **base-branch** definition instead.

All three ship in **one PR** (the "own deliberate PR" note on #3 only meant "don't fix it in
the PR that discovered it").

## 2. Decisions

| Decision | Choice |
|---|---|
| #1 fix | **Event-aware cutoff** — the cutoff advances only on content-change events (push, base change), never on `ready_for_review`. `reopened` is not a trigger at all (revised §8). |
| #2 fix | Listen to `edited` (base only); on base change **re-arm** and require *fresh* evidence on **both** paths |
| #2 re-review UX | **Block + instruct** — poll, then fail with a message to comment `@codex review` **and re-run the check** (the gate isn't re-triggered by comments/reviews; revised §8 C2). No auto-comment → workflow stays **read-only** |
| #3 fix | Switch `pull_request` → **`pull_request_target`** (runs base-branch definition); job stays metadata-only, no head checkout |
| Structure | Extract the decision logic to a **tested Python script**; YAML keeps the `gh api` fetch + poll loop |
| Permissions | Keep explicit **read-only** token (`contents`/`pull-requests`/`issues: read`), downgrading the write token `pull_request_target` grants by default |

## 3. Key insight — #1 and #2 are the same bug

Both are about **when the freshness cutoff should advance**. The clean-path check is "is
Codex's evidence newer than the cutoff?"; today the cutoff is always `updated_at`. That is
wrong in two directions:

- **#1:** the cutoff advances on `reopened` / `ready_for_review` although *no content
  changed* → valid evidence looks stale → false block.
- **#2:** the cutoff does *not* treat a base change as invalidating, and the SHA-pinned
  findings path has *no* freshness check at all → stale-green gate survives.

Unified rule: **the cutoff advances only on events that change what Codex must review — a
push or a base change — and both evidence signals must be newer than it.**

## 4. Architecture

### 4.1 Decision logic — new tested Python script

**New:** `.github/scripts/review_gate.py`

Pure function, no `gh` / network → fully unit-testable:

```text
decide(event_action, is_base_change, updated_at, head_sha, reviews, reactions) -> "pass" | "wait"

  content_change = event_action in {"opened", "synchronize"}
                   or (event_action == "edited" and is_base_change)

  if content_change:                      # cutoff = updated_at (push or base-change time)
      pass if  (∃ Codex review: commit_id == head_sha and submitted_at > updated_at)
            or (∃ Codex 👍:      created_at  > updated_at)
  else:                                   # reopened / ready_for_review — no content change
      pass if  (∃ Codex review: commit_id == head_sha)      # any timestamp
            or (∃ Codex 👍 exists)                           # any timestamp
      # (edited without base change never reaches here — filtered by the job `if:`)

  otherwise -> "wait"
```

- `main()` takes the event fields as CLI args (`--event-action`, `--is-base-change`,
  `--updated-at`, `--head-sha`) and reads `{"reviews": [...], "reactions": [...]}` from
  stdin; prints `pass` or `wait`. Mirrors the existing `.github/scripts/*.py` stdin/args
  convention (`detect_changes.py`, `validate.py`).
- Timestamps compared as ISO-8601 strings (lexicographic on UTC `Z` timestamps, as the
  current shell already does with `\>`), or parsed to epoch — implementation detail, covered
  by tests.

**New:** `.github/scripts/tests/test_review_gate.py` — one case per row of §4.2 plus the
races:
- post-push lingering 👍 (👍 present but older than push cutoff) → `wait`;
- base-change stale review (review@head but `submitted_at < cutoff`) → `wait`;
- `reopened` with a valid pre-existing 👍 (older than the inflated `updated_at`) → `pass`
  (the #1 regression guard);
- fresh 👍 / fresh review@head on a normal push → `pass`.

### 4.2 Decision table

| Event | `content_change`? | Cutoff | Passes when |
|---|---|---|---|
| `opened`, `synchronize` | yes | `updated_at` | review@head with `submitted_at > cutoff`, **or** 👍 `created_at > cutoff` |
| `edited` **with** `changes.base` | yes | `updated_at` (= base-change time) | same — an *old* review@head now fails freshness → waits for a fresh review |
| `ready_for_review` | no | none | review@head **exists**, or 👍 **exists** |
| `reopened` | — | **not a trigger** (revised §8) — prior check result persists | — |
| `edited` **without** base change | — | job skipped (`if:`) | — |

Adding `submitted_at > cutoff` to the findings path is what closes #2's stale-review hole and
is a no-op for normal pushes (a new head's review is always after the push).

### 4.3 YAML wrapper — `review-gate.yml`

```yaml
on:
  pull_request_target:              # #3: run the BASE-branch definition, not the PR's
    types: [opened, synchronize, ready_for_review, edited]   # `reopened` dropped — see §8

permissions:                        # least privilege; downgrades pull_request_target's write token
  contents: read
  pull-requests: read
  issues: read

concurrency:
  group: review-gate-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review-gate:
    name: review-gate
    # Same-repo only, and for `edited` only when the base actually changed.
    if: >-
      github.event.pull_request.head.repo.full_name == github.repository &&
      (github.event.action != 'edited' || github.event.changes.base != null)
    ...
```

The `run:` step is unchanged in shape — it keeps the two `gh api --paginate` calls (reviews +
reactions) and the sleep/timeout loop — but each iteration pipes the fetched JSON into
`review_gate.py` and branches on its `pass` / `wait` output. A persistent `wait` still fails
at the deadline; the failure message covers both "re-run once Codex finishes" and, for a base
change, "comment `@codex review` to request a fresh review."

`gh api` stays in shell (integration, not unit-tested); only the decision moves to Python.

### 4.4 #3 — `pull_request_target` safety

- `pull_request_target` runs the workflow file from the **base branch**, so a PR that edits
  `review-gate.yml` or `review_gate.py` can no longer alter the gate that guards its own
  merge — the trusted base version runs.
- **Safe** because the job is **metadata-only**: it never `actions/checkout`s or executes
  head code (the classic `pull_request_target` footgun). A comment in the workflow states
  this invariant so a future edit doesn't add a head checkout.
- Token stays explicitly read-only (`permissions:` block above), so even the base-branch job
  can't write.
- The required-check name `review-gate` is unchanged, so the `master` ruleset keeps gating
  without a settings change. `pull_request_target` still reports a check run on the PR's head
  SHA.
- The same-repo `if:` guard stays: `pull_request_target` fires for fork PRs too, but forks
  get no Codex app review and are skipped (a skipped required check is treated as satisfied).

## 5. Edge Cases & Mitigations

| Case | Behavior |
|---|---|
| Reopen a PR (head unchanged) | not a trigger — the head SHA's prior green check persists → mergeable (fixes #1 without re-running; revised §8). |
| Reopen after a while-closed push (head changed) | not a trigger — new SHA has no gate run → required check missing → **blocked** until a push/re-run (revised §8, closes C3). |
| Draft marked ready, already reviewed | `ready_for_review` → evidence exists → **pass**. |
| Draft marked ready, not yet reviewed | poll until Codex reviews (it triggers on ready) → **pass**; else deadline → fail. |
| Title/body edit | job `if:` skips (`changes.base == null`); the head SHA's prior passing status persists. |
| Base changed | re-arm; both paths require `> base-change time` → **wait** → fail with "comment `@codex review`". |
| Base changed then re-reviewed | fresh review@head / 👍 after the change → **pass**. |
| Lingering 👍 right after a push | `content_change=true`, 👍 `created_at < cutoff` → **wait** (unchanged behavior). |
| PR edits `review-gate.yml` to self-approve | base-branch definition runs (#3) → edit has no effect. |
| Fork PR | same-repo `if:` skips it (out of scope, as before). |

## 6. Testing

- **Unit:** `pytest` on `decide()` — the real safety net (every §4.2 row + §4.1 races).
  Run **locally** via `uv run pytest .github/scripts/tests/`. Note: `.github/scripts/tests`
  is not wired into CI or pre-commit today (only `packages/*/tests` run in CI), so these
  tests are a developer safety net, not a merge gate — consistent with the existing scripts
  tests. Wiring the scripts suite into CI is out of scope for this task.
- **Static:** `actionlint` on `review-gate.yml` (runs shellcheck on the `run:` block).
- **Lint/format/types:** `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`
  on the new script + test (per repo pre-commit workflow).
- **Post-merge live check** (noted in the PR): `pull_request_target` + base-branch execution
  can't be fully proven until the workflow is on the base branch. After merge, confirm on a
  follow-up PR that the `review-gate` check still reports and blocks, and that a base change
  re-arms it. Called out because it is the one step not verifiable pre-merge.

## 7. Out of Scope

- Quality-gate / fail-on-findings (still handled by "Require conversation resolution").
- Auto-posting `@codex review` on base change (chose block + instruct to stay read-only).
- Reviewing fork PRs.
- Any change to the Claude native `claude-review` check or the `master` ruleset.

## 8. Revision — 2026-07-03 (Codex round-5 review on PR #96)

Codex's review of the implementation PR found three valid holes in the original non-content
path (comments 3517637489 / 3517637493 / 3517637495):

- **C1** — a base change re-arms and blocks, but a later **close→reopen** (head unchanged)
  entered the non-content path and re-accepted the pre-base-change review@head → false green.
- **C3** — a 👍 is PR-level (not SHA-pinned). **Close → push new commits → reopen** let the
  `reopened` run accept the stale 👍 from the old SHA → false green for the new SHA.
- **C2** — on a base-change timeout, following the message (`@codex review`) makes Codex post
  a review, but the workflow isn't triggered by comments/reviews, so the required check stays
  red until someone re-runs it.

**Resolution (all in PR #96, no durable-cutoff redesign):**

1. **Drop `reopened` from the triggers.** Both C1 and C3 are exploited *through* the
   `reopened` event. With it removed, a reopen doesn't re-run the gate: the head SHA's prior
   check result persists. This closes C1 and C3 (a reopen can no longer launder stale evidence
   into a fresh green) **and** fixes the original #1 false-block more cleanly — a still-valid
   green just persists instead of being re-evaluated against an inflated `updated_at`. A reopen
   whose head genuinely changed has no gate run for the new SHA, so the required check is
   missing and merge stays **blocked** (safe: false-block, never false-green). GitHub has no
   repo-level setting to forbid reopening a PR, so this workflow-level drop is the mechanism.
   The non-content path now serves only `ready_for_review` (a draft's head SHA can't change
   invisibly — pushes to a draft fire `synchronize` — so a bare 👍 there is trustworthy).
2. **C2 message.** The timeout error now states the check is not re-triggered by Codex
   comments/reviews and must be re-run manually once Codex finishes — on the base-change path,
   comment `@codex review` first, then re-run.

Residual (accepted): a base change *on a draft* followed by marking it ready could still
accept a pre-base-change review@head via `ready_for_review`. Very narrow; not worth a durable
cutoff. `ready_for_review` is kept because it's needed for the draft→ready flow to trigger a
gate run.
