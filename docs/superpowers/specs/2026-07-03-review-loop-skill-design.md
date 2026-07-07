# Design: review-loop — cyclic PR review-comments processing

- **Task:** claude-tools-elf.23 (currently under the Flow epic; this design **re-scopes it to
  `#repo`** — see "Task re-scope" below)
- **Date:** 2026-07-03
- **New skill:** `.claude/skills/review-loop/` — **project-local, committed** to claude-tools
- **Reuses (unchanged):** `plugins/flow/skills/review-comments/SKILL.md`
- **Depends on repo checks:** `claude-review` + `review-gate` (review anchors, defined in
  `.github/workflows/`) plus the PR's CI checks (lint/test), all keyed to the head SHA. On PRs,
  CI lint (ruff-format / ruff / ty) posts findings as **inline review comments** via reviewdog
  (`github-pr-review`), so they arrive as ordinary review threads authored by
  `github-actions[bot]`

## Problem

The bot-driven review cycle on a claude-tools PR is: push → Claude + Codex re-review the head →
they drop findings → fix → push → they re-review → … until nothing new comes back. The delta
between a push and the next batch of bot findings is small and predictable (≤ ~20 min, bounded
by the `review-gate` Codex poll of ~12 min + Claude's check).

Today `flow:review-comments` handles **one** batch and exits. Riding the bot cycle to
convergence means re-invoking it by hand every round. That manual re-trigger is the friction
this task removes.

The human-review path is deliberately **out of scope for the loop**: a human reviewer's
reaction time is unbounded (hours/days), so those comments are handled by calling
`flow:review-comments` standalone, without a loop.

## Goal

A project-local `/review-loop` skill that wraps the fast bot cycle: after each push it waits
for the repo's review gates to finish re-reviewing the new head, then — if the bots produced
new findings — runs `flow:review-comments` on them, and repeats until the bots go quiet. One
invocation instead of N.

## Non-goals

- **Touching `flow:review-comments`.** It stays a single-pass, interactive, reply-only skill,
  callable standalone for the slow human path. The loop calls it verbatim.
- **Resolving threads or merging.** The loop is reply-only like `review-comments`; resolving
  conversations and merging stay manual (the `master` ruleset's conversation-resolution
  requirement is satisfied by the human).
- **Fixing threadless check failures.** Linter findings CI posts as inline review comments
  (ruff/ty via reviewdog) are ordinary actionable threads and *are* fixed by the loop. But a
  failure with **no** inline thread — a failing test, a build error, or plugin-lint run without
  reviewdog — can't be handed to `review-comments`; the loop surfaces it and leaves the fix to
  the user (linters run locally pre-push, so this is a rare safety net).
- **GitLab / other repos.** The loop is GitHub-only and hard-wired to this repo's gates. A
  portable, config-driven version was considered and rejected as premature (YAGNI) — only this
  repo has these gates today. It can be promoted to a flow-plugin skill later if a second repo
  grows the same gates.
- **A hard round cap.** Replaced by a round indicator (see below).

## Key insight

The gates give a **precise "re-review of this head is complete" signal**, which is strictly
better than the time-based "quiet window" polling a generic loop would need (that guesses, and
can trip on half-delivered rounds). Two gates carry the signal:

- `claude-review` — Claude's native check-run; **re-runs on every push**, so its `completed`
  state means "Claude has reviewed this head."
- `review-gate` — a **commit status** (context `review-gate`) posted to the head SHA by
  `.github/workflows/review-gate.yml`. That workflow itself polls Codex (👀 → 👍 / review) and
  posts `pending → success|failure|error`. A terminal (non-`pending`) status means "Codex has
  reviewed this head."

Convergence is then a comment-level test layered on top of that timing signal: **after the
gates for the latest head are terminal, are there any actionable threads left?** Zero → the
bots are satisfied, we're done.

**Wait for the whole pipeline, not just the two review gates.** The head SHA also runs CI
(Python/plugin lint, tests, etc.). The loop waits until *every* check for the head is terminal
— the two review gates **plus** all CI checks — using the review gates as guaranteed-present
anchors so it never concludes on a not-yet-started empty set. Review is the long pole (Codex
~12 min; linters run locally pre-push and rarely outlast it), so this almost never adds
latency. It is also **necessary for correctness**: CI posts ruff/ty findings as *inline review
comments* (reviewdog `github-pr-review`, authored by `github-actions[bot]`), so they are
ordinary actionable threads — counting threads before the lint job finishes would miss them and
converge early. Only failures with **no** inline thread (a failing test, a build error, or
plugin-lint run without reviewdog) are surfaced for the user to fix; the loop can't hand those
to `review-comments`.

## Design

### Placement & invocation

- `.claude/skills/review-loop/SKILL.md` — the skill (prompt), invoked as `/review-loop [PR#]`.
  The `.claude/` directory does not exist yet; it is created and tracked in git.
- `.claude/skills/review-loop/bin/wait-for-checks.sh` — the pipeline-wait helper, in a `bin/`
  subfolder **mirroring the flow plugin's `plugins/flow/bin/` layout**, with a smoke test in
  `.claude/skills/review-loop/bin/tests/` (same pattern as `plugins/flow/bin/tests/`). Unlike
  the plugin's `bin/` (which the plugin puts on `PATH`, so helpers are called as bare
  `flow-*` commands), this project-local helper has no PATH injection — the skill calls it by
  path relative to its injected base directory (`<skill-base>/bin/wait-for-checks.sh`). The
  `bin/` layout is kept purely for repo consistency.
- `allowed-tools`: `Bash(gh:*) Bash(git:*) Bash(*/bin/wait-for-checks.sh:*) Skill
  AskUserQuestion Read`. `Skill` is required so the loop can invoke `flow:review-comments` each
  iteration. (Verify the exact `allowed-tools` grammar for the path-based helper and for
  invoking a skill during implementation.)

### The loop (wait-first framing)

```
/review-loop [PR#]:
  0. Resolve the open PR for the current branch (reuse review-comments Phase 1:
     gh pr view --json number,headRefName,url,state). No open PR -> stop.
  1. ROUND = 0
  2. loop:
       HEAD = current head SHA (git rev-parse HEAD after any sync)
       # a. wait until the WHOLE pipeline for HEAD is terminal (review gates + CI/linters)
       wait-for-checks.sh <PR> <HEAD>       # returns: all-terminal (+ per-check conclusions) | timeout
         - on timeout: ask the user (wait more / process what's there / stop)
       failed = checks whose conclusion is failure/error (from the helper output)
       # b. is there new review work?
       actionable = count_actionable(PR)    # unresolved threads NOT yet replied-to by us
       if actionable == 0:
         if failed is empty:
           report clean convergence + summary; STOP   # review quiet AND pipeline green
         else:
           report "review converged, but CI red: <failed>"; ask user (fix manually / stop)
       # c. process this round
       ROUND += 1
       print "── Раунд ROUND · head <HEAD:7> · actionable: <K> ──"
       flag any thread seen in a previous round as "⚠️ <ref> — повторно (N-й раунд)"
       invoke Skill flow:review-comments <PR>       # interactive; may push a new head
       # review-comments' own Phase 3 (Process all N?) and Phase 5.6 (Push?) are the
       # in-round control points. Answering "no" in Phase 3 exits the loop.
  # terminators: convergence (2b) · PR merged/closed (checked each iteration) · user Esc
```

**Entry is uniform.** On the first pass the loop waits for the gates on the *current* head:
if you just pushed code and ran `/review-loop`, it waits for the first review; if the bots
already commented, `wait-for-checks.sh` returns immediately.

**No-push round.** If `review-comments` changes no code (e.g., it replied "Won't fix" to
everything), HEAD is unchanged. Next iteration `wait-for-checks.sh` returns instantly (the
gates for that SHA are already terminal), and `actionable` is now 0 (we replied to those
threads), so the loop converges. It never blocks waiting for a re-review that won't happen.

### wait-for-checks.sh (pipeline-wait helper)

Contract: `wait-for-checks.sh <PR> <HEAD_SHA>` → blocks until the **whole check pipeline for
that exact SHA** is terminal, then exits 0 and prints one line per check
(`<context> <conclusion>`); exits non-zero on timeout.

**Keyed by SHA — this is the whole point.** Immediately after a push the previous head's checks
may still read green while the new run hasn't registered; a PR-level `gh pr checks --watch`
would return "all passed" prematurely. The helper queries by the pushed SHA and treats the two
review gates as **guaranteed-present anchors** so it can't conclude on a not-yet-started empty
set:

- **Anchor 1 — `claude-review`:** `gh api repos/{o}/{r}/commits/{HEAD_SHA}/check-runs` → the
  check-run with context `claude-review` exists and `status == "completed"`.
- **Anchor 2 — `review-gate`:** `gh api repos/{o}/{r}/commits/{HEAD_SHA}/status` → a status with
  context `review-gate` exists and its `state ∈ {success, failure, error}` (not `pending`).
- **Rest of the pipeline:** every other check-run for the SHA is `completed` and the combined
  status `.state` is not `pending` (all CI/lint/test contexts settled).
- All three hold → exit 0, emitting each check's `conclusion` (so the skill can spot failures).
  Else `sleep INTERVAL`.
- Own deadline `TIMEOUT` (⚙️ ~15 min — review is the long pole at ~12 min; CI/linters run
  locally pre-push and rarely outlast it), `INTERVAL` ⚙️ 30 s. On deadline → exit 2 so the skill
  can ask the user rather than hang forever.

(The anchor context strings — `claude-review`, `review-gate` — are confirmed from
`review-gate.yml`; re-verify with `gh pr checks` during implementation in case a run name
differs from its required-context name.)

### "New" thread definition & convergence

- An **actionable** thread = an unresolved review thread we have **not yet replied to**. That
  is exactly `review-comments`' own actionable set — its `already_replied` filter carries the
  cross-round state, so **no separate state file is needed**.
- **Linter findings are actionable threads too.** On PRs, CI runs ruff-format / ruff / ty
  through reviewdog with reporter `github-pr-review`, which posts each finding as an inline
  review comment authored by `github-actions[bot]`. `review-comments` collects and classifies
  these as bot comments like any other, so the loop fixes lint findings through the normal path
  — no special handling. (This is why waiting for the lint job to finish is required *before*
  counting actionable threads.)
- **Convergence == actionable set empty** after the whole pipeline for the head is terminal
  (with no threadless red check — otherwise it's the "review converged, CI red" hand-off).
- The loop can compute `count_actionable` with a light `gh api` + `jq` pass over the PR's
  review comments/threads (root threads where the latest note is not from us and the thread
  isn't resolved), reusing the same filter logic `review-comments` Phase 2 documents. It does
  **not** need to run the full Phase 2 subagent just to count.

### Round indicator (replaces a hard cap)

There is no `max_rounds` auto-stop. Instead, each processing round prints a header:

```
── Раунд 3 · head a1b2c3d · actionable: 2 ──
⚠️ C3 — повторно (3-й раунд)
⚠️ CI: Python CI (statuskit) — failure
```

- The **round number** and **head SHA** give progress at a glance.
- Any **failing check** (from `wait-for-checks.sh`) is surfaced as a `⚠️ CI:` line for
  visibility. Reviewdog lint checks (ruff/ty) will additionally have their findings in the
  actionable list — the loop fixes those normally; a check **still red at convergence** (a
  failing test/build with no thread) is the genuine hand-off-to-user case.
- A thread whose ID reappears in a later round is flagged **повторно** with the count. This is
  the human-visible signal for a bot ↔ "Won't fix" ping-pong (a reviewer re-replying to a
  dismissal makes the thread actionable again). Repeat-tracking is in-session memory (a set of
  processed thread IDs held by the agent across iterations); no persistence.
- Safety comes from the session being **interactive**: `review-comments` asks for confirmation
  every round (Phase 3 process-confirm, Phase 5.6 push-confirm), so the loop can never spin
  silently — and the user presses Esc the moment the indicator shows an unproductive dispute.

### Reuse contract with review-comments

- The loop invokes `flow:review-comments <PR>` via the `Skill` tool once per round; no flags,
  no non-interactive mode (that option was explicitly rejected — `review-comments` stays
  untouched).
- No double confirmation: the loop auto-enters `review-comments` when it detects actionable
  threads; `review-comments`' existing Phase 3 / Phase 5.6 prompts remain the control points.
- Late human comments are not special-cased: if one appears while the loop runs, it lands in
  the actionable set and gets processed like any bot thread. Because convergence is scoped to
  bot latency, a slow human comment that arrives after convergence is handled by a fresh
  standalone `review-comments` call — matching the two-timing-regime model.

### Task re-scope

`claude-tools-elf.23` sits under the **Flow Improvements** epic (`#flow`). Since the
deliverable is a **repo-local skill** (not a change to the flow plugin), the work is `#repo`:

- PR title/label: `#repo` scope (e.g., `feat: add review-loop project skill`).
- Re-parent the task under the **Repo-level** epic (`claude-tools-5vg`) — do this at
  `/flow:decompose` or `/flow:done` time.

## Testing & validation

- **Helper (`wait-for-checks.sh`)**: a smoke test in the `plugins/flow/bin/tests/` style —
  feed it recorded `check-runs` / `status` fixtures (via a stubbed `gh`) and assert it (a)
  blocks while any check is `pending`/`in_progress`, (b) blocks until the `claude-review` and
  `review-gate` anchors are present (never concludes on an empty/not-yet-started set), (c)
  returns once all checks are terminal and emits each `conclusion`, and (d) keys on the right
  SHA (old head green, new head pending → keep waiting).
- **Skill (prompt-only)**: validate via `superpowers:writing-skills` (frontmatter + structure)
  and a dry-run walkthrough of the loop against a real PR — confirm: entry waits for the
  current head's gates; a productive round processes and pushes; a no-push "Won't fix" round
  converges instead of hanging; the repeat flag fires on a re-opened thread.

## Risks

- **Wrong/renamed check context.** If `claude-review` or `review-gate` are renamed, the helper
  waits until timeout. Mitigation: the timeout surfaces to the user (not a hang), and the
  contexts are asserted against `review-gate.yml` + re-verified with `gh pr checks` at
  implementation.
- **Dispute ping-pong.** A reviewer re-replying to a "Won't fix" keeps a thread actionable and
  the loop keeps offering it. Mitigation: the **повторно** indicator + interactive per-round
  confirmations + Esc — a deliberate human decision, not an infinite machine loop.
- **Gate timing outliers.** Codex occasionally exceeds the ~12 min norm (the helper now waits
  for the slowest check across the whole pipeline, but review stays the long pole). The
  helper's ~15 min timeout then asks the user (wait more / process now / stop) rather than
  declaring false convergence.
- **Threadless red check.** A failing *test* or *build* (or plugin-lint run without reviewdog)
  produces no inline thread, so `review-comments` can't fix it. The loop surfaces it every
  round and, at convergence, refuses to declare a clean finish — it reports "review converged,
  CI red: <checks>" and hands off to the user instead of silently ending green. (Ruff/ty lint
  *does* post inline comments and is fixed normally.)
- **Project-skill discovery.** `.claude/skills/` project-scoped skills must be auto-discovered
  as `/review-loop`; confirm the mechanism during implementation (fallback: document manual
  enablement).

## Open defaults (⚙️ — confirm at implementation)

- `wait-for-checks.sh` timeout ~15 min, poll interval 30 s.
- Convergence counted by a light in-skill `gh api`+`jq` pass, not the full Phase 2 subagent.
