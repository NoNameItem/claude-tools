---
name: review-loop
description: "Use when you have pushed to a claude-tools GitHub PR and want the automated bot review cycle (Claude claude-review, Codex review-gate, CI ruff/ty lint comments) addressed round after round to convergence, instead of re-invoking flow:review-comments by hand each time. GitHub-only, hard-wired to this repo's review gates. Reply-only: it never resolves threads or merges. Not for GitLab, other repos, or human-reviewer feedback."
allowed-tools: Skill(flow:review-comments) Bash(gh:*) Bash(git:*) Bash(${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py:*) Read
---

# Review Loop

## Overview

**Core principle:** wait for a *precise* "this exact head has been re-reviewed" signal, then process only what's new — repeat until the bots go quiet.

`/review-loop [PR#]` rides the fast bot review cycle on a **claude-tools GitHub PR**:
push → Claude (`claude-review`) + Codex (`review-gate`) re-review the head and CI
posts ruff/ty findings as inline comments → fix → push → they re-review → … until
nothing new comes back. Doing that by hand means re-running `flow:review-comments`
every round; this skill runs the cycle for you with one invocation.

It **reuses `flow:review-comments` verbatim** each round (no flags, no
non-interactive mode). That skill's own confirmations are the control points: its
Phase 3 ("Process all N?") and its push confirmation — both **plain-text prompts
that wait for your typed answer** (it bans structured dialogs for the same
AFK-safety reason this skill does). The loop never pushes silently and never
processes without your go-ahead.

## When to use

- You just pushed to a claude-tools GitHub PR and want the bot/CI review cycle
  ridden to convergence without babysitting it.

## When NOT to use

- **Human review.** A human reviewer's reaction time is unbounded (hours/days).
  Handle those with a standalone `flow:review-comments` call, not the loop.
- **Non-claude-tools repos / GitLab.** Hard-wired to this repo's `claude-review`
  + `review-gate` gates. GitHub-only.
- **To make the PR mergeable.** The loop is **reply-only**. Convergence means
  "the bots have nothing new to say," NOT "ready to merge." Resolving review
  threads and merging stay **yours to do** (the `master` ruleset's
  conversation-resolution requirement is satisfied by a human). See red flags.

## The loop

### 0. Resolve the PR

Reuse `flow:review-comments` Phase 1:

```bash
gh pr view [PR#] --json number,title,headRefName,url,state,headRefOid
```

- No open PR for the branch → stop.
- Found → show number, title, URL; set `ROUND = 0` and continue.

### 1. Each iteration

**a. Capture `HEAD_before`** — the exact commit the gates run on (SHA-keyed, so
there is no stale-data race; a brand-new SHA simply starts with no checks yet):

```bash
HEAD_before=$(gh pr view <PR> --json headRefOid -q .headRefOid)
```

**b. Stop if the PR is closed/merged:**

```bash
STATE=$(gh pr view <PR> --json state -q .state)   # OPEN | MERGED | CLOSED
```

Not `OPEN` → report and stop.

**c. Wait for the whole pipeline for `HEAD_before` to be terminal** (both review
gates + all CI), using the tested helper — do NOT hand-roll the poll:

```bash
${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py <PR> <HEAD_before>
```

- Exit 0 → prints one line per check (`<name> <conclusion>`); record as `failed`
  any whose conclusion is **not** `success`, `neutral`, or `skipped` (i.e.
  `failure`, `error`, `cancelled`, `timed_out`, `action_required`, `stale`).
- Exit 1 → usage error (a bug in how the skill called it); fix the call, don't
  treat it as a timeout.
- Exit 2 (timeout) → ask the user with a **plain-text numbered prompt** — **never
  `AskUserQuestion`** (its AFK auto-submit would act with no real answer; see red
  flags). Print:

  ```
  Проверки для <HEAD_before:0:7> не завершились за отведённое время. Что делать?
  1. Подождать ещё
  2. Обработать то, что есть сейчас
  3. Остановиться
  ```

  Wait for a typed reply. **2 (process what's there now)** marks this round
  **PARTIAL** — the pipeline is not terminal, so this round can never be a clean
  convergence (step g), because lint/bot comments may still arrive.
- Exit 3 (head moved) → the branch advanced during the wait, so `HEAD_before` is
  stale (an external push, or master auto-merged into the branch). Loop back to
  step (a) to re-capture the head and re-wait on the **new** head — do not run
  review-comments or converge on the stale head.

Waiting for CI here is **not** because CI gates merge (only `claude-review` and
`review-gate` do) — it is because CI posts ruff/ty findings as inline review
comments, so running review-comments before the lint job finishes would miss them
and converge early. On the **first** pass this waits for the current head's first
review; if the bots already commented, the helper returns immediately.

**d. Red-pipeline gate.** If `failed` is **non-empty**, the pipeline for this head
has a red check. Surface the red checks and ask with a **plain-text numbered
prompt** (never `AskUserQuestion`):

```
Пайплайн для <HEAD_before:0:7> завершился с красными проверками:
  ✗ <name> — <conclusion>
Что делать?
1. Всё равно запустить review-comments (разобрать инлайн-треды)
2. Остановиться (чиню руками, потом перезапущу /review-loop)
```

- **1** → continue to (e). Remember that `failed` was non-empty — at convergence
  (g) it **colors the final report** (not a clean finish).
- **2** → stop: "Остановился — проверка `<name>` красная, чини руками, потом
  перезапусти `/review-loop`."

Why offer "run anyway": reviewdog lint findings (ruff/ty) arrive as ordinary
inline threads that review-comments *can* fix, so processing them is often
productive even while a check is red. A **threadless** red check (a failing
test/build, or plugin-lint without reviewdog) has no thread review-comments can
fix — that is the genuine hand-off, and it colors the final report at (g).

**e. Run review-comments.**

- `ROUND += 1`. Print the round indicator:

  ```
  ── Раунд <ROUND> · head <HEAD_before:0:7> ──
  ```

  For any `failed` check from step (c), add a `⚠️ CI: <name> — <conclusion>`
  line. For any comment ref review-comments printed in an earlier round (its
  Phase 2 table / Phase 5.7 summary, visible in-context because review-comments
  runs via the **Skill** tool in this same agent), add a `⚠️ <ref> — повторно
  (<N>-й раунд)` line. Repeat-tracking is in-session memory (a set of refs seen
  across iterations); no GraphQL, no persistence.

- Invoke `flow:review-comments <PR>` via the **Skill** tool. It is interactive and
  may push a new head. Answering "no" at its Phase 3 exits the loop. If you skip
  its push (Phase 5.6), any replies are posted but its fixes stay **local** — the
  PR head is unchanged; step (g)'s unpushed-commit check surfaces this.

**f. Capture `HEAD_after`:**

```bash
HEAD_after=$(gh pr view <PR> --json headRefOid -q .headRefOid)
```

**g. Decide convergence — purely by push** (`HEAD_after` vs `HEAD_before`):

- `HEAD_after != HEAD_before` (review-comments pushed) → **loop** back to (a) to
  wait for the gates on the new head. Nothing else to decide — a push always means
  another review round.
- `HEAD_after == HEAD_before` (no push this round) → this round converges. Before
  reporting, **check for unpushed local commits** (review-comments may have
  committed a fix locally but skipped its push):

  ```bash
  LOCAL_HEAD=$(git rev-parse HEAD)
  ```

  If `LOCAL_HEAD` != `HEAD_after` (local is ahead of the PR's remote head), warn —
  this must be surfaced, not silently converged:

  ```
  ⚠️ Есть локальные коммиты, не запушенные на PR (local <LOCAL_HEAD:0:7> ≠ remote <HEAD_after:0:7>).
     review-comments ответил «Fixed», но фиксы остались локально. Запушь их и перезапусти /review-loop.
  ```

  Then STOP with the reason that fits:
  - round **PARTIAL** (step c timed out and you chose "process now") → **partial
    hand-off:** "обработал что было, но пайплайн для `<HEAD_before:0:7>` не добежал
    (wait timed out) — перезапусти `/review-loop`, когда проверки завершатся." Not
    a clean finish.
  - round **not** PARTIAL, `failed` **empty** → **clean convergence.** Report a
    short summary and remind the user that **resolving the threads and merging are
    theirs to do** (the loop is reply-only).
  - round **not** PARTIAL, `failed` **non-empty** (you came through gate (d) option
    1, or a threadless red check) → **red-check hand-off:** "остановился, проверка
    `<name>` красная — чини руками." Not a clean finish.

### Terminators

No open PR at resolve (0) · clean convergence (1g) · partial hand-off (1g) ·
red-check hand-off (1g) · PR merged/closed (1b) · user "stop" at the timeout
prompt (1c) · user "stop" at the red-pipeline gate (1d) · user "no" at
`flow:review-comments` Phase 3 · user Esc.

## Round indicator (replaces a hard cap)

There is **no** `max_rounds` auto-stop and no wall-clock cap. Safety comes from
the loop being interactive — `flow:review-comments` confirms every round (process
+ push) — plus the visible round indicator. A bot ↔ "Won't fix" ping-pong shows
up as a comment ref that `flow:review-comments` prints again in a later round
(its per-round output is visible in-context, since it runs via the **Skill**
tool in this same agent), flagged `повторно` with the round count. The user
presses Esc the moment the indicator shows an unproductive dispute. A machine
round cap would just as often cut off a productive cycle mid-flight; the human
decision is better.

## Quick reference

| Step | Command / action | Key point |
|------|------------------|-----------|
| Head SHA | `gh pr view <PR> --json headRefOid -q .headRefOid` | capture `HEAD_before` (a) and `HEAD_after` (f) |
| State | `gh pr view <PR> --json state -q .state` | not `OPEN` → stop (b) |
| Wait | `${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py <PR> <HEAD>` | whole pipeline; exit 2=timeout (PARTIAL), 3=head moved (restart) |
| Red gate | `failed` non-empty → plain-text run-anyway / stop | before review-comments (d) |
| Process | Skill `flow:review-comments <PR>` | verbatim, interactive |
| Converge | `HEAD_after` vs `HEAD_before`; `git rev-parse HEAD` for unpushed | push→loop; no push→stop + warn if local ahead (g) |

## Red flags — STOP

- "I'll add a `max_rounds` / wall-clock cap so it can't run forever." → **No.**
  Use the round indicator + interactivity; a hard cap cuts off productive cycles.
  The human's Esc is the stop.
- "Convergence means the PR is ready — I'll resolve the threads and/or merge." →
  **No.** Reply-only. Resolving conversations and merging are the human's job; do
  not add a `resolveReviewThread` sweep or a merge step.
- "I'll run `flow:review-comments` non-interactively / with a flag." → It's
  reused verbatim, interactive. No flags, no bypass of its push confirmation.
- "I'll count actionable threads myself (GraphQL / `jq`) to decide convergence."
  → **No.** review-comments owns "actionable"; the loop converges purely on the
  **push** comparison (`HEAD_after` vs `HEAD_before`). Do not reintroduce a thread
  count — that is exactly what this redesign removed.
- "No push this round, so we're cleanly done — I'll just stop." → First compare
  `git rev-parse HEAD` with `HEAD_after`. If local is ahead, review-comments
  committed a fix but its push was skipped; warn (step 1g), don't declare clean.
- "I'll run `flow:review-comments` before the pipeline finishes." → Wait for the
  whole pipeline first (step c), or ruff/ty inline comments land after you've
  already processed the round.
- "The wait returned 0, so the head I captured is still current." → Not
  guaranteed — the branch can advance mid-wait. The helper exits 3 when it does;
  on exit 3, restart from step (a).
- "A required check is red but no comments — I'll loop `flow:review-comments`
  until it turns green." → It structurally can't fix a threadless red check.
  Surface it at the red gate (1d) and let it color the final report (1g).
- "I'll use `AskUserQuestion` for the timeout / red-gate prompt — it's cleaner."
  → **No.** Its AFK auto-submit can act with no real answer from the user, who
  often runs sessions unattended. Use plain-text numbered prompts (steps 1c, 1d).
  This skill declares no `AskUserQuestion` in `allowed-tools`.
- "This is a GitLab MR / another repo." → GitHub + this repo only. Stop.

## Common mistakes

- **Converging clean over an unpushed fix.** review-comments applied a fix,
  committed locally, but its push was skipped → the remote head is unchanged so a
  naive check reads "no push → converged", while the "Fixed:" replies now sit on
  a PR that lacks the fix. Compare `git rev-parse HEAD` with `HEAD_after` and warn
  (step 1g).
- **Running review-comments before CI lint posts its comments.** Processing before
  `Python CI`'s reviewdog run finishes misses a whole class of findings. The
  step-(c) wait exists precisely to prevent this.
- **Re-introducing a thread count.** review-comments is the single source of truth
  for "actionable"; the loop decides by push. Do not add back a GraphQL or `jq`
  pass — the `allowed-tools` no longer grant `jq` for this reason.
- **Pushing mid-review.** Never push while `wait_for_checks.py` hasn't returned
  for the current head — a push mid-poll wastes the in-flight Codex cycle.
  Structurally prevented by only entering step (e) after step (c) returns.
