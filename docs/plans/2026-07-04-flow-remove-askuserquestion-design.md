# Design: Remove AskUserQuestion from flow (prose-only interactive prompts)

**Task:** claude-tools-6q4
**Date:** 2026-07-04
**Supersedes:** `2026-02-09-askuserquestion-branch-design.md` (commit `c48cba5`, PR #61) — that
design introduced `AskUserQuestion` for branch selection; this one removes it.

## Problem

In `flow:start` (and other flow skills), branch/worktree/push decisions are asked via the
`AskUserQuestion` tool. When the user does not answer within an idle timeout, the Claude Code
harness **auto-submits the pre-selected option** and injects a synthetic result:

> "No response after 60s — the user may be away from keyboard. Proceed using your best judgment…"

The model then treats this as consent and performs **irreversible actions without the user's
agreement**: creates a branch/worktree, changes task status/assignee, or — in `review-comments` —
pushes to the remote. The user works across several parallel sessions, so a 60-second gap means
"busy elsewhere," not "away" and not "approve the recommended option."

## Root cause (verified against Claude Code docs)

This is the built-in **AFK (away-from-keyboard) auto-continue** for `AskUserQuestion`:

- The multiple-choice dialog auto-submits its **pre-selected (first) option** after
  `CLAUDE_AFK_TIMEOUT_MS` (default **60000 ms**); a countdown shows in the last 20 s
  (`CLAUDE_AFK_COUNTDOWN_MS`). Any keypress or a focused window resets the timer.
- It applies **only to the `AskUserQuestion` tool dialog**. Plain-text ("prose") questions —
  where the model ends its turn with a question and waits for the next user message — and
  permission prompts (incl. plan approval) are **never** auto-resolved.
- Introduced in CLI **v2.1.198**. In **v2.1.200** (2026-07-03) the default flipped to *no longer
  auto-continue by default; opt into an idle timeout via `/config`*. A user on v2.1.200 who still
  sees auto-continue has the idle timeout opted-in (likely carried over from the pre-2.1.200
  default on upgrade).
- Controls besides `CLAUDE_AFK_TIMEOUT_MS`: `/config` (exact key name undocumented; inspect via
  `/config --help`) and keeping the terminal focused. **No** `settings.json` key and **no** CLI
  flag exist for it (verified negative).

### Why this is new

Two independent recent changes had to coincide; neither alone is sufficient:

| Side | Change | When |
|------|--------|------|
| Harness | AFK auto-continue for `AskUserQuestion` added | v2.1.198 |
| Flow | Branch selection migrated from prose → `AskUserQuestion` tool | commit `c48cba5` (#61) |

Before #61, branch selection was plain text and structurally immune to the timeout, even after the
harness feature existed. `superpowers` never triggers this because it asks entirely in prose (no
`AskUserQuestion` tool call anywhere in its skill bodies); `flow:continue` and `flow:decompose`/
`flow:done` are likewise prose already.

## Goal / success criteria

1. No flow skill emits an `AskUserQuestion` tool call. Every interactive choice is a plain-text,
   numbered prompt that ends the turn and waits — structurally immune to AFK auto-continue.
2. Behavior on an injected AFK/no-response fallback: never create branches/worktrees, never change
   task/repo state, never push. (Achieved structurally — there is nothing for the harness to
   auto-submit.)
3. Regression is caught automatically (CI) and explained where it matters (on-site comments +
   CONTRIBUTING).

## Scope

### Sites to convert (grounded via grep)

| Skill | Site | What AFK auto-submit would do | Risk |
|-------|------|-------------------------------|------|
| `start` | Step 6 branch/worktree selection | create branch/worktree, change status | high |
| `review-comments` | 5.6 push confirmation | `git push` unattended | high |
| `review-comments` | `disagree` reply (per comment) | post a rebuttal to the PR | medium |
| `review-comments` | `agree_unclear` (per comment) | decide whether to apply a fix | medium |
| `review-comments` | platform GitHub/GitLab (ambiguous fallback) | pick wrong platform (fails loudly) | low |

Plus: remove `AskUserQuestion` from the `allowed-tools:` frontmatter of `start`, `continue`, and
`review-comments`.

### Deliberately unchanged

- `continue` — Step 7b already uses a prose numbered choice (serves as the canonical template).
- `decompose`, `done` — no `AskUserQuestion`.
- `start` task selection and takeover — already prose.
- `start` Step 5.5 auto-resolve — orthogonal to `AskUserQuestion`; kept as-is.

## Design decisions

- **Q1 — full removal (chosen).** One rule: flow never uses `AskUserQuestion`. Rejected: surgical
  removal (keeps a judgment call about "what is irreversible" and leaves one live dialog to guard);
  keep-tool-plus-guard (relies on the model disobeying the harness's explicit "proceed" and on
  undocumented option-ordering behavior).
- **Q2 — maximum regression protection (chosen).** CI invariant + on-site comments + a rule in
  CONTRIBUTING / skill-authoring docs. Rejected: fix-only (would regress exactly as #61 did);
  invariant-only (misses the "why").
- **Q3 — preserve semantic invariants, drop the matrices (chosen).** Keep the meaning as explicit
  bullet rules; discard the per-case `AskUserQuestion` option-matrix tables, which were artifacts of
  the structured tool.

### What we give up vs. keep

`AskUserQuestion` was added in #61 purely for convenience (click instead of typing free-text
answers). We consciously trade that click-affordance back for AFK-safety. The **auto-resolve** cases
(Step 5.5) that #61 also introduced are independent of the tool and are kept — they still skip the
question entirely when the answer is obvious.

## Conversion convention (prose)

A single lightweight convention everywhere, matching `flow:continue` Step 7b: emit the question and
numbered options inside a fenced block, then end the turn and wait for an answer by number (or free
text — prose is inherently free-form, so the old "Other" branch disappears).

Semantic invariants, preserved as explicit bullet rules rather than option tables:

- On a generic branch (master/develop/…): mark the recommended option (e.g. `1. … — рекомендую`).
- When "stay on the current branch" is offered on a generic branch: warn ("master держим чистым").
- Offer the worktree option **only** when `IN_WORKTREE=false`.
- When `flow-find-branches` returns matches: surface them ("также найдены: …") and prefer the
  local branch as the primary option.
- On a feature branch: neutral tone, no explicit recommendation.

## Per-skill changes

### `start` Step 6

Replace the `AskUserQuestion` call and its option matrix with a prose template modeled on
`continue` Step 7b, carrying the invariants above (recommendation, conditional worktree option,
existing-branch note, stay-on-branch warning). Remove the "Other (free-form input)" subsection.
Steps 5.5 (auto-resolve) and 7 (takeover, already prose) are untouched.

### `review-comments`

Each site becomes "ask in plain text, then wait," offering the same options currently shown:

- **5.6 push confirmation** → prose `1. Push / 2. Skip` with the change/commit summary. This is the
  intent of the global "confirm before push" rule; prose is strictly safer here because AFK on this
  dialog is an unattended auto-push. The skill's "MANDATORY: Use AskUserQuestion … (per CLAUDE.md
  global instructions)" line is updated to say the confirmation is a plain-text prompt and why.
- **`agree_unclear`** (per comment) → prose numbered options (incl. "Skip this comment").
- **`disagree`** (per comment) → prose numbered options (Accept / Reject / Discuss further); "Discuss
  further" is naturally supported by prose conversation.
- **platform detection** → prose GitHub/GitLab choice (or instruct the user to pass `--platform`).

### `allowed-tools`

Drop `AskUserQuestion` from the frontmatter of `start`, `continue`, `review-comments`.

## Regression guard

- **CI invariant:** a check fails if any `plugins/flow/skills/**/SKILL.md` contains the token
  `AskUserQuestion`. Wired into the existing plugin CI (exact job pinned in the implementation
  plan). This is also the structural RED→GREEN test (currently RED; GREEN after conversion).
- **On-site comments:** a short rationale line at each converted prompt — "prose by design —
  AskUserQuestion auto-submits on AFK timeout; see claude-tools-6q4".
- **CONTRIBUTING / skill-authoring rule:** flow skills must not use `AskUserQuestion`; it
  auto-submits the pre-selected option after the idle timeout (`CLAUDE_AFK_TIMEOUT_MS`, default 60s;
  harness v2.1.198+), which for branch/push/status prompts is an irreversible action without
  consent. Ask via plain-text numbered prompts (template: `flow:continue` Step 7b). User-side knob
  to disable the harness behavior: `/config` or `CLAUDE_AFK_TIMEOUT_MS`.

## Personal global config (out of repo, done separately)

The "ALWAYS use AskUserQuestion to confirm before `git push`" rule lives only in the user's personal
`~/.claude/CLAUDE.md` — not in this repo and not on this branch. It has been softened separately to
prefer a plain-text push confirmation (same reasoning). Not part of the committed change; noted here
for traceability.

## Testing (writing-skills TDD)

- **Structural (= the CI invariant):** grep for `AskUserQuestion` under `plugins/flow/skills/`;
  RED before conversion, GREEN after. Doubles as the permanent regression guard.
- **Behavioral (dogfood):** a subagent given the converted `start` skill produces a prose branch
  prompt and does **not** call `AskUserQuestion`; when handed a simulated AFK/no-response fallback,
  it creates no branch and mutates no state. A skeptic subagent checks the converted skills for
  consistency (no leftover AUQ references, invariants preserved, `allowed-tools` cleaned).

## Out of scope

- Changing harness behavior (not possible from a plugin).
- `statuskit`.
- Editing the user's personal `~/.claude/CLAUDE.md` as a repo deliverable (done separately, above).

## References

- Superseded design: `docs/plans/2026-02-09-askuserquestion-branch-design.md`; commit `c48cba5` (#61).
- Canonical prose template: `plugins/flow/skills/continue/SKILL.md` Step 7b.
- Claude Code docs: tools-reference (AskUserQuestion idle timeout), env-vars
  (`CLAUDE_AFK_TIMEOUT_MS`, `CLAUDE_AFK_COUNTDOWN_MS`), changelog (v2.1.198 intro, v2.1.200 default
  flip).
