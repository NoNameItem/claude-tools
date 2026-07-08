---
name: review-loop
description: "Use after pushing to a GitHub Pull Request or GitLab Merge Request when you want the automated bot/CI review cycle ridden round after round to convergence, instead of re-invoking flow:review-comments by hand each round. Cross-platform (gh/glab), gate-name-agnostic. Reply-only: it never resolves threads or merges. Not for human-reviewer feedback."
allowed-tools: Skill(flow:review-comments) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(flow-wait-ci:*) Read
---

# Review Loop

## Overview

**Core principle:** wait for a *precise* "this exact head has been re-reviewed" signal, then process only what's new — repeat until the bots go quiet.

`/flow:review-loop [number]` rides the fast bot/CI review cycle on a **GitHub PR or
GitLab MR**: push → the review bots re-review the head and CI posts lint findings as
inline comments → fix → push → they re-review → … until nothing new comes back. Doing
that by hand means re-running `flow:review-comments` every round; this skill runs the
cycle for you with one invocation.

It **reuses `flow:review-comments` verbatim** each round (no flags, no non-interactive
mode). That skill's own confirmations are the control points: its Phase 3 ("Process all
N?") and its push confirmation — both **plain-text prompts that wait for your typed
answer** (it bans structured dialogs for AFK-safety; this skill does the same). The loop
never pushes silently and never processes without your go-ahead.

Convergence is decided **purely by push** (did the head SHA advance this round), never by
counting threads — so it is platform-agnostic by construction.

## When to use

- You just pushed to a PR/MR and want the bot/CI review cycle ridden to convergence
  without babysitting it.

## When NOT to use

- **Human review.** A human reviewer's reaction time is unbounded (hours/days). Handle
  those with a standalone `flow:review-comments` call, not the loop.
- **To make the PR/MR mergeable.** The loop is **reply-only**. Convergence means "the bots
  have nothing new to say," NOT "ready to merge." Resolving review threads and merging stay
  **yours to do**. See red flags.

## Platform + PR/MR resolution

Resolve the platform and the PR/MR **exactly as `flow:review-comments` does** — do not
re-invent it:

- **Platform:** `flow:review-comments` Phase 0 "Detection algorithm" (`--platform` override
  → remote host → `gh`/`glab` auth-host match → heuristic → ask). Store `PLATFORM`.
- **PR/MR + repo:** `flow:review-comments` Phase 1 (repo identifier; the PR number / MR
  iid; branch sync). "PR/MR" means "Pull Request on GitHub, Merge Request on GitLab" —
  use the platform-appropriate word in output; MRs are referenced by **iid**.

Per-platform primitives used below:

| | GitHub (`gh`) | GitLab (`glab`) |
|---|---|---|
| Head SHA | `gh pr view <n> --json headRefOid -q .headRefOid` | `glab mr view <iid> --output json` → `.sha` (the MR diff head SHA; matches what `flow-wait-ci` polls) |
| State | `gh pr view <n> --json state -q .state` → `OPEN`/`MERGED`/`CLOSED` | `glab mr view <iid> --output json` → `.state` → `opened`/`merged`/`closed` |
| Local head | `git rev-parse HEAD` | `git rev-parse HEAD` |

## The loop

### 0. Resolve

Resolve `PLATFORM` + the PR/MR (above). No open PR/MR → stop. Found → show number/iid,
title, URL; set `ROUND = 0` and continue.

### 1. Each iteration

**a. Capture `HEAD_before`** — the exact commit the gates run on (SHA-keyed, so there is no
stale-data race; a brand-new SHA simply starts with no checks yet). Use the platform's
head-SHA command above.

**b. Stop if the PR/MR is closed/merged.** Use the platform's state command. GitHub: not
`OPEN` → stop. GitLab: not `opened` → stop.

**c. Wait for the whole pipeline for `HEAD_before` to be terminal**, using the tested
helper by **bare name** — do NOT hand-roll the poll and do NOT reference any absolute path:

```bash
flow-wait-ci <number> <HEAD_before> --platform <PLATFORM>
```

- **Exit 0** → prints one line per check. Compute `failed`:
  - GitHub (`<name> <conclusion>`): record as `failed` any whose second token is **not**
    `SUCCESS`/`NEUTRAL`/`SKIPPED` (case-insensitive) — i.e. failure/error/cancelled/etc.
  - GitLab (`pipeline <status>` + `<job> failed`): record as `failed` any line whose second
    token is **not** `success`/`skipped`/`manual`/`scheduled` — i.e. `failed`/`canceled`.
    (Blocking `manual`/`scheduled` are terminal-for-waiting but do **not** trip the red-gate.)
- **Exit 1** → usage error (a bug in how the skill called it), not a timeout. **Stop the
  loop** and report the malformed `flow-wait-ci` invocation to the user; do **not** retry
  automatically — retrying the same bad call just fails again.
- **Exit 2 (timeout)** → ask with a **plain-text numbered prompt** — **never a structured
  dialog** (its AFK auto-submit would act with no real answer; claude-tools-6q4). Print:

  ```
  Проверки для <HEAD_before:0:7> не завершились за отведённое время. Что делать?
  1. Подождать ещё
  2. Обработать то, что есть сейчас
  3. Остановиться
  ```

  Wait for a typed reply. **1** → re-run `flow-wait-ci` (loop step c). **2** marks this
  round **PARTIAL** (the pipeline is not terminal, so this round can never be a clean
  convergence — lint/bot comments may still arrive). Because the pipeline never went
  terminal, `flow-wait-ci` emitted **no** per-check lines, so `failed` is empty/unknown for
  this round → **skip the red-gate (d)** (do not consult `failed`) and go straight to (e);
  the **PARTIAL** flag alone colors the final report at (g). **3** → stop.
- **Exit 3 (head moved)** → the branch advanced during the wait, so `HEAD_before` is stale
  (an external push, or an automatic merge into the branch). Loop back to step (a) to
  re-capture the head and re-wait on the **new** head — do not run review-comments or
  converge on the stale head.
- **Exit 4 (no CI/bots)** → after the grace window there is no pipeline/checks on this head
  at all. There is nothing to ride:

  ```
  На этом PR/MR нет CI/ботов-ревьюеров (проверки не появились). Цикл review-loop нечего
  крутить — обрабатывай комментарии вручную через flow:review-comments, если они есть.
  ```

  Stop with that explanation. (This is the generalization beyond a gated repo: an arbitrary
  PR/MR may have no CI/bots, and a silent "clean convergence" would lie — "bots have nothing
  to say" ≠ "there are no bots".)

Waiting for CI here is **not** because CI gates merge — it is because CI posts lint findings
as inline review comments, so running review-comments before the lint job finishes would
miss them and converge early. On the **first** pass this waits for the current head's first
review; if the bots already commented, the helper returns immediately.

**d. Red-pipeline gate.** If `failed` is **empty**, continue silently to (e). If `failed` is
**non-empty**, the pipeline for this head has a red check. Surface the red checks and ask
with a **plain-text numbered prompt** (never a structured dialog):

```
Пайплайн для <HEAD_before:0:7> завершился с красными проверками:
  ✗ <name> — <conclusion/status>
Что делать?
1. Всё равно запустить review-comments (разобрать инлайн-треды)
2. Остановиться (чиню руками, потом перезапущу /flow:review-loop)
```

- **1** → continue to (e). Remember `failed` was non-empty — at convergence (g) it **colors
  the final report** (not a clean finish).
- **2** → stop: "Остановился — проверка `<name>` красная, чини руками, потом перезапусти
  `/flow:review-loop`."

Why offer "run anyway": lint findings arrive as ordinary inline threads that review-comments
*can* fix, so processing them is often productive even while a check is red. A **threadless**
red check (a failing test/build) has no thread review-comments can fix — that is the genuine
hand-off, and it colors the final report at (g).

**e. Run review-comments.**

- `ROUND += 1`. Print the round indicator:

  ```
  ── Раунд <ROUND> · head <HEAD_before:0:7> ──
  ```

  For any `failed` check from step (c), add a `⚠️ CI: <name> — <conclusion>` line. For any
  comment ref review-comments printed in an earlier round (its Phase 2 table / Phase 5.7
  summary, visible in-context because review-comments runs via the **Skill** tool in this
  same agent), add a `⚠️ <ref> — повторно (<N>-й раунд)` line. Repeat-tracking is in-session
  memory (a set of refs seen across iterations); no API queries, no persistence.

- Invoke `flow:review-comments <number>` via the **Skill** tool. It is interactive and may
  push a new head. Answering "no" at its Phase 3 exits the loop. If you skip its push (Phase
  5.6), any replies are posted but its fixes stay **local** — the head is unchanged; step
  (g)'s unpushed-commit check surfaces this.

**f. Capture `HEAD_after`** — the platform's head-SHA command again.

**g. Decide convergence — purely by push** (`HEAD_after` vs `HEAD_before`):

- `HEAD_after != HEAD_before` (review-comments pushed) → **loop** back to (a) to wait for the
  gates on the new head. A push always means another review round.
- `HEAD_after == HEAD_before` (no push this round) → this round converges. Before reporting,
  **check for unpushed local commits** (review-comments may have committed a fix locally but
  skipped its push):

  ```bash
  LOCAL_HEAD=$(git rev-parse HEAD)
  ```

  If `LOCAL_HEAD != HEAD_after`, warn — surface it, do not silently converge:

  ```
  ⚠️ Есть локальные коммиты, не запушенные на PR/MR (local <LOCAL_HEAD:0:7> ≠ remote <HEAD_after:0:7>).
     review-comments ответил «Fixed», но фиксы остались локально. Запушь их и перезапусти /flow:review-loop.
  ```

  Then STOP with the reason that fits:
  - round **PARTIAL** (step c timed out, you chose "process now") → **partial hand-off:**
    "обработал что было, но пайплайн для `<HEAD_before:0:7>` не добежал (wait timed out) —
    перезапусти `/flow:review-loop`, когда проверки завершатся." Not a clean finish.
  - round **not** PARTIAL, `failed` **empty** → **clean convergence.** Report a short summary
    and remind the user that **resolving the threads and merging are theirs to do** (the loop
    is reply-only).
  - round **not** PARTIAL, `failed` **non-empty** (gate (d) option 1, or a threadless red
    check) → **red-check hand-off:** "остановился, проверка `<name>` красная — чини руками."
    Not a clean finish.

### Terminators

No open PR/MR at resolve (0) · clean convergence (1g) · partial hand-off (1g) · red-check
hand-off (1g) · no CI (`exit 4`, 1c) · internal usage error from `flow-wait-ci` (`exit 1`,
1c) · PR/MR merged/closed (1b) · user "stop" at the timeout prompt (1c) · user "stop" at the
red-pipeline gate (1d) · user "no" at `flow:review-comments` Phase 3 · user Esc.

## Round indicator (replaces a hard cap)

There is **no** `max_rounds` auto-stop and no wall-clock cap. Safety comes from the loop
being interactive — `flow:review-comments` confirms every round (process + push) — plus the
visible round indicator. A bot ↔ "Won't fix" ping-pong shows up as a comment ref that
`flow:review-comments` prints again in a later round (its per-round output is visible
in-context, since it runs via the **Skill** tool in this same agent), flagged `повторно` with
the round count. The user presses Esc the moment the indicator shows an unproductive dispute.
A machine round cap would just as often cut off a productive cycle mid-flight; the human
decision is better.

## Quick reference

| Step | Command / action | Key point |
|------|------------------|-----------|
| Resolve | review-comments Phase 0/1 | platform + PR/MR; "PR/MR" per platform |
| Head SHA | gh `headRefOid` / glab `.sha` | capture `HEAD_before` (a) and `HEAD_after` (f) |
| State | gh `.state`/glab `.state` | not open → stop (b) |
| Wait | `flow-wait-ci <n> <HEAD> --platform <p>` | whole pipeline; 2=timeout(PARTIAL), 3=head moved(restart), 4=no CI(stop) |
| Red gate | `failed` non-empty → plain-text run-anyway / stop | before review-comments (d) |
| Process | Skill `flow:review-comments <n>` | verbatim, interactive |
| Converge | `HEAD_after` vs `HEAD_before`; `git rev-parse HEAD` for unpushed | push→loop; no push→stop + warn if local ahead (g) |

## Red flags — STOP

- "I'll add a `max_rounds` / wall-clock cap so it can't run forever." → **No.** Use the round
  indicator + interactivity; the human's Esc is the stop.
- "Convergence means it's ready — I'll resolve the threads and/or merge." → **No.**
  Reply-only. Resolving conversations and merging are the human's job.
- "I'll run `flow:review-comments` non-interactively / with a flag." → It's reused verbatim,
  interactive. No flags, no bypass of its push confirmation.
- "I'll count actionable threads myself to decide convergence." → **No.** review-comments owns
  "actionable"; the loop converges purely on the **push** comparison.
- "No push this round, so we're cleanly done — I'll just stop." → First compare
  `git rev-parse HEAD` with `HEAD_after`. If local is ahead, warn (step 1g).
- "I'll run `flow:review-comments` before the pipeline finishes." → Wait for the whole
  pipeline first (step c), or lint inline comments land after you've processed the round.
- "The wait returned 0, so the head I captured is still current." → Not guaranteed — the
  branch can advance mid-wait. The helper exits 3 when it does; on exit 3, restart from (a).
- "Exit 4 but I'll just converge clean." → **No.** No CI/bots ≠ bots-had-nothing-to-say.
  Stop with the exit-4 explanation.
- "A required check is red but no comments — I'll loop until it turns green." → It
  structurally can't fix a threadless red check. Surface it at (1d), let it color the report.
- "I'll use a structured multiple-choice dialog for the timeout / red-gate / exit-4 prompt —
  it's cleaner." → **No.** Its AFK auto-submit can act with no real answer (claude-tools-6q4).
  Use plain-text prompts; this skill grants no such dialog tool in `allowed-tools`.
- "I'll hardcode the wait helper path / a specific gate name." → **No.** Call `flow-wait-ci`
  by bare name; it is gate-name-agnostic.

## Common mistakes

- **Converging clean over an unpushed fix.** review-comments applied a fix, committed
  locally, but its push was skipped → the remote head is unchanged so a naive check reads "no
  push → converged". Compare `git rev-parse HEAD` with `HEAD_after` and warn (step 1g).
- **Running review-comments before CI lint posts its comments.** The step-(c) wait exists
  precisely to prevent this.
- **Re-introducing a thread count.** review-comments is the single source of truth for
  "actionable"; the loop decides by push.
- **Pushing mid-review.** Never push while `flow-wait-ci` hasn't returned for the current
  head — a push mid-poll wastes the in-flight review cycle. Structurally prevented by only
  entering step (e) after step (c) returns.
- **Assuming GitHub.** Resolve the platform first (review-comments Phase 0); the wrong CLI
  fails on the first command.
