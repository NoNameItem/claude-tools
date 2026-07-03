---
name: review-loop
description: Use when you have pushed to a claude-tools GitHub PR and want the automated bot review cycle (Claude claude-review, Codex review-gate, CI ruff/ty lint comments) addressed round after round to convergence, instead of re-invoking flow:review-comments by hand each time. GitHub-only, hard-wired to this repo's review gates. Reply-only: it never resolves threads or merges. Not for GitLab, other repos, or human-reviewer feedback.
allowed-tools: Skill(flow:review-comments) Bash(gh:*) Bash(jq:*) Bash(${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py:*) AskUserQuestion Read
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
non-interactive mode). That skill's own confirmations are the control points:
its Phase 3 ("Process all N?") and Phase 5.6 ("Push?" via `AskUserQuestion`). The
loop never pushes silently and never processes without your go-ahead.

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

**a. Get the head SHA** — the exact commit the gates run on (SHA-keyed, so there
is no stale-data race; a brand-new SHA simply starts with no checks yet):

```bash
HEAD=$(gh pr view <PR> --json headRefOid -q .headRefOid)
```

**b. Stop if the PR is closed/merged:**

```bash
STATE=$(gh pr view <PR> --json state -q .state)   # OPEN | MERGED | CLOSED
```

Not `OPEN` → report and stop.

**c. Wait for the whole pipeline for HEAD to be terminal** (both review gates +
all CI), using the tested helper — do NOT hand-roll the poll:

```bash
${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py <PR> <HEAD>
```

- Exit 0 → prints one line per check (`<name> <conclusion>`); note as `failed`
  any whose conclusion is **not** `success`, `neutral`, or `skipped` (i.e.
  `failure`, `error`, `cancelled`, `timed_out`, `action_required`, `stale`).
- Exit 2 (timeout) → ask the user (`AskUserQuestion`): **wait more** / **process
  what's there now** / **stop**.
- Exit 1 → usage error (a bug in how the skill called it); fix the call, don't
  treat it as a timeout.

Waiting for CI here is **not** because CI gates merge (only `claude-review` and
`review-gate` do) — it is because CI posts ruff/ty findings as inline review
comments, so counting threads before the lint job finishes would miss them and
converge early.

On the **first** pass this waits for the current head's first review; if the bots
already commented, the helper returns immediately.

**d. Count actionable threads** — unresolved inline threads whose latest comment
is not from us. This mirrors `flow:review-comments`' inline `already_replied` set
(latest reply author == you), so it carries cross-round state with no state file.
A thread you already answered ("Fixed" / "Won't fix") drops out; if a bot pushes
back, its latest author flips and it becomes actionable again:

```bash
ME=$(gh api user -q .login)
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
ACTIONABLE=$(gh api "repos/$OWNER_REPO/pulls/<PR>/comments?per_page=100" --paginate --slurp \
  | jq --arg me "$ME" '
      add                                    # --slurp wraps pages; add merges them
      | map({root: (.in_reply_to_id // .id), login: .user.login, created_at: .created_at})
      | group_by(.root)
      | map(max_by(.created_at).login)
      | map(select(. != $me))
      | length')
```

> A bot **review body with no inline comment** (a summary-only finding) has no
> inline reply target and is rare on this repo; the count scopes to inline
> threads, and `flow:review-comments` surfaces any summary item in its own report
> when it runs.

**e. Converge or process:**

- `ACTIONABLE == 0`:
  - `failed` empty → the bots are quiet. Report convergence + a short summary,
    and remind the user that **resolving the threads and merging are theirs to
    do** (the loop is reply-only). **STOP.**
  - `failed` non-empty → a threadless red check: a required check still red with
    no inline thread `flow:review-comments` can fix (a `claude-review`/Codex
    failure with no comment, a failing test, or a plugin-lint failure — plugin
    lint runs plain `ruff check` with no reviewdog, so it posts no comments).
    Report "the bots are quiet, but a check is red: `<failed>`" and ask the user
    (fix manually / stop). Do **not** declare a clean finish.
- `ACTIONABLE > 0`: process this round (step f).

**f. Process the round:**

- `ROUND += 1`. Print the round indicator:

  ```
  ── Раунд <ROUND> · head <HEAD:0:7> · actionable: <ACTIONABLE> ──
  ```

  For any `failed` check from step (c), add a `⚠️ CI: <name> — <conclusion>`
  line. For any thread ID seen in a previous round, add a `⚠️ <ref>
  — повторно (<N>-й раунд)` line (repeat-tracking is in-session memory: a set of
  processed thread IDs held across iterations; no persistence).

- Invoke `flow:review-comments <PR>` via the **Skill** tool. It is interactive
  and may push a new head. Answering "no" at its Phase 3 exits the loop.

- Loop back to step (a).

### Terminators

Convergence (1e) · PR merged/closed (1b) · user Esc · user answers "no" at
`flow:review-comments` Phase 3.

## Round indicator (replaces a hard cap)

There is **no** `max_rounds` auto-stop and no wall-clock cap. Safety comes from
the loop being interactive — `flow:review-comments` confirms every round (process
+ push) — plus the visible round indicator. A bot ↔ "Won't fix" ping-pong shows
up as a thread flagged `повторно` climbing in round count, and the user presses
Esc the moment the indicator shows an unproductive dispute. A machine round cap
would just as often cut off a productive cycle mid-flight; the human decision is
better.

## Quick reference

| Step | Command / action | Key point |
|------|------------------|-----------|
| Head SHA | `gh pr view <PR> --json headRefOid -q .headRefOid` | SHA-keyed, no stale race |
| Wait | `${CLAUDE_SKILL_DIR}/bin/wait_for_checks.py <PR> <HEAD>` | whole pipeline; don't hand-roll |
| Count | `gh api .../pulls/<PR>/comments` + jq | latest-comment-not-mine |
| Converge | actionable 0 & no red check | bots quiet ≠ mergeable |
| Process | Skill `flow:review-comments <PR>` | verbatim, interactive |

## Red flags — STOP

- "I'll add a `max_rounds` / wall-clock cap so it can't run forever." → **No.**
  Use the round indicator + interactivity; a hard cap cuts off productive cycles.
  The human's Esc is the stop.
- "Convergence means the PR is ready — I'll resolve the threads and/or merge." →
  **No.** Reply-only. Resolving conversations and merging are the human's job;
  do not add a `resolveReviewThread` sweep or a merge step.
- "I'll run `flow:review-comments` non-interactively / with a flag." → It's
  reused verbatim, interactive. No flags, no bypass of its push confirmation.
- "I'll count actionable threads before CI lint finishes." → Wait for the whole
  pipeline first (step c), or ruff/ty comments land after you've declared clean.
- "I'll poll a time-based quiet window instead of the gates." → Use
  `wait_for_checks.py`; the gates are a precise per-head signal.
- "A required check is red but no comments — I'll loop `flow:review-comments`
  until it turns green." → It structurally can't fix a threadless check. Surface
  it as a hand-off (step 1e), don't spin.
- "This is a GitLab MR / another repo." → GitHub + this repo only. Stop.

## Common mistakes

- **Converging early.** Counting threads before `Python CI`'s lint job posts its
  reviewdog comments → you miss a whole class of findings. The step-(c) wait
  exists precisely to prevent this.
- **Re-arguing settled threads.** If you invent your own "seen" tracking instead
  of the latest-comment-not-mine rule, you'll re-process threads you already
  answered. Use the step-(d) count as the single source of truth.
- **Pushing mid-review.** Never push while `wait_for_checks.py` hasn't returned
  for the current head — a push mid-poll wastes the in-flight Codex cycle.
  Structurally prevented by only entering step (f) after step (c) returns.
