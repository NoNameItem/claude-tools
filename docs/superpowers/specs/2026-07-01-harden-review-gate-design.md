# Harden review-gate: freshness cutoff, base-change, self-modification — Design

**Date:** 2026-07-01 (revised 2026-07-03 — see §8, §9, §10)
**Status:** Implemented on PR #96. **§10 is the current design** (de-scoped to #1 + #3 after
three rounds of Codex review; base-change #2 dropped as an accepted limitation). §9 = the
publish-mechanism redesign it builds on; §8 = the reopen drop; §4 = superseded first cut.
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

> **Superseded in part by §9 (Revision 2).** §4.1–§4.4 describe the first implementation
> (event-aware `decide()`, job-check-run gate). Codex's review of that implementation found
> the job-check-run gate is bypassable/misplaced under `pull_request_target`; §9 replaces the
> publish mechanism (explicit head-SHA status) and collapses `decide()` to a single cutoff
> check. Read §9 for the current design; §4 is kept for history.

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

## 9. Revision 2 — 2026-07-03 (Codex round-6 review on PR #96) — CURRENT DESIGN

Codex's next review found three more valid P1 holes, two of them in the *publish* mechanism
(comments 3518194399 / 3518194401 / 3518194408):

- **C4** — `ready_for_review` accepted a bare 👍 from an earlier head (the §8 residual, now
  treated as a real bypass): a stale clean reaction can green an unreviewed draft once ready.
- **C5** — a non-base title/body edit hits the job-level `if:` → **a skipped job reports
  success, and a skipped required check satisfies branch protection** → a no-op edit replaces
  a red/pending gate with green for the same head SHA, no Codex evidence.
- **C6** — under `pull_request_target`, `GITHUB_SHA` is the base branch, so the job's own check
  run is attributed to the **base** SHA, while required checks are evaluated on the **PR head**
  SHA. The gate never produces the required result on the head → it can't function as a
  required check (a regression vs the working `pull_request` gate on `master`).

**Resolution — publish an explicit head-SHA status + a single-cutoff `decide()`:**

1. **The required check is a commit status posted to the head SHA, not the job's check run.**
   The job `POST`s a status with context `review-gate` to `pull_request.head.sha`
   (`pending` → `success`/`failure`). This lands on the head SHA regardless of `GITHUB_SHA`
   (**fixes C6**). The job is renamed `review-gate-poll` so a skipped/absent job can never
   produce the required `review-gate` context (**fixes C5**); a non-base edit now safely skips
   (nothing posted → the head SHA's prior status persists). `permissions:` gains
   `statuses: write` (narrow; still no head-code execution — the `pull_request_target`
   base-only checkout invariant is unchanged). The `master` ruleset still requires the string
   `review-gate`; a status with that context satisfies it, so **no ruleset change** is needed.
2. **`decide()` collapses to one freshness check** — `decide(cutoff, head_sha, reviews,
   reactions)`: pass iff a Codex review@head or a Codex 👍 is **strictly newer than `cutoff`**.
   The content/non-content branching (the source of C1/C3/C4) is gone. The workflow computes
   the cutoff per event: `updated_at` (push / base-change time) for content-change events, and
   the **head commit's committer date** for `ready_for_review` (**fixes C4** — a stale 👍 from
   an earlier head predates the current head's committer date and is rejected; the committer
   date is safe here because marking ready is not a push, so the concurrent-push race that
   bars committer dates on `synchronize` can't occur). `reopened` remains dropped (§8).
3. **Forks** are handled inside the job (they can't be Codex-gated): post `success`
   ("Fork PR — Codex gate not applicable") and exit, preserving the previous
   skip-as-satisfied behavior now that a skipped job no longer yields the required context.
4. **No `concurrency`.** Because each run posts its status only to its own frozen `HEAD_SHA`,
   a commit pushed mid-poll is already race-safe: a new `synchronize` starts a fresh run for
   the new SHA, and the in-flight poll can only ever settle the *old* SHA (never the head).
   `cancel-in-progress: true` would be actively harmful — an unrelated `edited` (title/body)
   event would cancel a live poll and strand its `pending` status; `cancel-in-progress: false`
   would serialize and make a new push wait up to the full timeout behind a stale poll. So the
   concurrency block is removed. The tradeoff is that rapid pushes leave superseded polls
   running to their timeout (they post only to superseded SHAs — harmless).

Updated decision table (replaces §4.2):

| Event | Cutoff | Head-SHA status posted |
|---|---|---|
| `opened`, `synchronize`, `edited`+base | `updated_at` | poll → `success` if review@head/👍 `> cutoff`, else `failure` at deadline |
| `ready_for_review` | head commit committer date | same rule against that cutoff |
| `edited` without base | — | job skipped → nothing posted → prior status persists |
| `reopened` | — | not a trigger → prior status persists |
| fork PR (any event) | — | `success` (out of scope, honest description) |

CLI change: `review_gate.py` now takes `--cutoff` + `--head-sha` (was
`--event-action/--updated-at/--head-sha/--base-changed`).

Post-merge caveat still applies and is now sharper: because this PR changes the gate's own
trigger/publish model, the `review-gate` status won't report on #96 itself — verify on the
first follow-up PR after merge that the head-SHA `review-gate` status posts and blocks.

## 10. Revision 3 — 2026-07-03 (Codex round-7) — de-scope base-change (#2). CURRENT DESIGN

Codex's review of the §9 redesign found four more issues, three of them (P1) all rooted in
**base-change / draft-ready freshness** (comments 3518606809 / 3518606821 / 3518606817) plus
a real P2 crash (3518606813):

- **809 / 821** — the `ready_for_review` committer-date cutoff is itself unsafe: it can predate
  a later base change (809) or a pre-existing 👍 whose commit was authored earlier (821), so
  stale evidence passes.
- **817** — dropping `concurrency` (§9.4) is unsound *for base changes*: retargeting keeps the
  same head SHA, so a pre-base-change `synchronize` poll can post a stale `success` that
  overwrites the base-change run's failure on the same status context.
- **813 (P2)** — a *pending* Codex review has `submitted_at: null`; `None > cutoff` raised a
  `TypeError`, killing the poll and stranding the `pending` status.

**Diagnosis:** three review rounds each spawned fresh P1s, all in the base-change (#2) /
draft-ready freshness area. A correct fix needs a durable, monotonic per-head cutoff with
read-modify-write on the status — distributed-systems machinery for a *completion* gate whose
real security is human review + conversation-resolution. Poor ROI, and exactly the endless
inline-review loop this task (cna) was created to avoid.

**Resolution — de-scope #2:**

1. **Drop the `edited`/base-change trigger and handling** (the committer-date `ready_for_review`
   cutoff, the base-change `if:` filter, `BASE_CHANGED`). Triggers are now only
   `[opened, synchronize]`. This removes 809, 821, **and** 817 outright: with no base change,
   no two runs ever target the same head SHA, so the per-SHA isolation reasoning (no
   `concurrency`) holds again. **Accepted limitation:** a base-branch change leaves the prior
   `review-gate` status in place (the original defect #2) — rare on a trusted-collaborator
   repo, and human review + conversation-resolution still gate; documented, not fixed.
2. **Drop `ready_for_review`** — there is no safe stateless freshness cutoff for it. A draft is
   gated by its `opened`/`synchronize` runs; a draft that needs a fresh gate after being marked
   ready must be pushed again or the check re-run. Accepted limitation.
3. **Fix P2 (813):** `decide()` coerces a missing/`null` timestamp to `""` (`(x or "") > cutoff`)
   so a pending review is treated as not-fresh, never a crash. Covered by two new tests.

What survives from the original scope: **#1** (freshness cutoff for the normal push flow),
**#3** (self-modification defence via `pull_request_target` + base-only checkout, published as
an explicit head-SHA status per §9), and the reopen drop (§8, closing C1/C3). Only **#2**
(base-change re-arm) is dropped.

Final design in one line: on `opened`/`synchronize`, `pull_request_target` runs the base
definition, polls Codex, and POSTs a `review-gate` status to the head SHA — `success` iff a
Codex review@head or 👍 is newer than the push time, else `failure` at the deadline; forks are
skipped; reopen/edited/ready_for_review are not triggers.

## 11. Revision 4 — 2026-07-03 (Codex round-8) — status-mechanism hardening

Three more findings, this time on the §10 publish mechanism itself (not the base-change swamp)
— all cleanly bounded (comments 3518798827 / 3518798831 / 3518798822):

- **827 (P1)** — commit statuses are keyed by (SHA, context), not by PR. The fork `success`
  bypass could post a green `review-gate` to a head SHA a *same-repo* PR also points at, greening
  its gate with no Codex evidence. **Fix:** skip forks entirely (`if: head.repo == repo`); a
  fork PR's `review-gate` stays missing (blocked) rather than falsely green. (Behaviour change:
  fork PRs are no longer auto-mergeable — acceptable; forks are out of scope and rare here.)
- **831 (P1)** — with no `concurrency`, a poll for old SHA A still running after a push to SHA B
  can accept B's PR-level 👍 (newer than A's cutoff) and post `success` to A; that green on the
  reusable (SHA, context) status could later satisfy another PR at A. **Fix:** before posting
  `success`, re-fetch `pulls/{n}.head.sha` and bail if the PR no longer points at this run's
  `HEAD_SHA`.
- **822 (P2)** — after `pending`, any `set -e` failure (transient gh/jq/python) exited without a
  terminal status, stranding the head at `pending`. **Fix:** an `EXIT` trap posts `error` when
  the run exits non-zero before a terminal status was posted (guarded by a `RESULT_POSTED` flag
  so it never overwrites a real success/failure).

These harden the mechanism without reopening the freshness/cutoff design; §10's one-line summary
still holds (with "forks are skipped" and the stale-poll head re-check).

**Round-9 follow-up (comment 3518919030, P2):** the stale-poll re-check (831) exited without a
terminal status, leaving the superseded SHA at `pending`. Now the stale branch posts `failure`
("Superseded — PR advanced to a newer head") before exiting, and guards the head compare on a
non-empty API result so a transient blip can't be read as "moved". Inherent, accepted residual:
commit statuses are keyed by (SHA, context), so two PRs sharing a head SHA share the gate status
— unusual, and out of scope.
