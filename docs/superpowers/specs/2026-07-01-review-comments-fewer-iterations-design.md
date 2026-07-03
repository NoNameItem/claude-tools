# Design: Improve flow:review-comments to reduce review iterations

- **Task:** claude-tools-k4f
- **Date:** 2026-07-01
- **Skill:** `plugins/flow/skills/review-comments/SKILL.md` (single-file, prompt-only)

## Problem

The `review-comments` skill processes PR/MR review threads: analyze each comment, apply
accepted fixes, argue against invalid ones, reply, commit, push. On PR #89 (the review-gate
work) this loop spiraled to ~4 Codex review rounds. The retro found three root causes:

1. **Layer-by-layer patching.** One deep problem (a freshness cutoff — "is this 👍 for the
   head SHA?") was patched per-event-type instead of solved once for the whole class.
2. **Shallow dismissal.** A valid P1 was misdiagnosed as "already handled" on a shallow read:
   the analyzer pattern-matched "a timestamp comparison exists" instead of checking *what* it
   compared against (the wrong reference). Cost a full rework round.
3. **Fixes shifted the bug next door.** A local fix moved the defect to the adjacent case
   (committer-date → `updated_at` exposed the review-event cutoff). Compounded because an
   on-push reviewer re-reviews every push, so discovery was serialized one issue at a time.

## Goal

Cut the number of review rounds by changing the skill so it (a) reads deeply before
dismissing, (b) fixes the whole class at once, and (c) simulates the next reviewer round
locally before the single push.

## Non-goals

- **Push cadence** — untouched. The skill already batches every accepted fix into one round
  and pushes once (Phase 5.5). The retro's "push-per-fix" was PR #89's *manual* reality, not a
  skill defect. Change 4 is the mitigation: catch the next round locally, before that push.
- Resolving/dismissing threads (skill stays reply-only).
- The `allowed-tools` audit — separate task (claude-tools-elf.22).

## Design

Five changes, all inside the existing `SKILL.md`. No new top-level tools: subagents run
`grep` / `git diff` via `Agent`, so the skill's `allowed-tools` is unchanged.

### Change 1 — Analyzer on sonnet (Phase 4)

Every Phase 4 analysis subagent moves from `model="haiku"` to `model="sonnet"`;
`subagent_type` stays `"Bash"`. Uniform, no tiering. This targets root cause #2 directly — the
model that read shallowly is replaced by a more capable one on every comment.

### Change 2 — Verdict discipline: no shallow dismissals (Phase 4)

Restructure the verdict the analysis subagent returns. For **any `disagree` or
`outdated_fixed`** verdict, two fields become mandatory:

- `CLAIM:` — the comment's specific claim, restated in the analyzer's own words.
- `EVIDENCE:` — the exact code (`file:line` + snippet) that makes *that* claim moot.

Baked-in anti-pattern: **"a related mechanism exists" is not evidence.** The evidence must
address the specific claim — not "a timestamp comparison is present" but "it compares against
`updated_at` at `file:line`, which is the reference the comment says is wrong." **If the claim
cannot be proven moot, the verdict must be `agree`, not `disagree`/`outdated_fixed`.**

Add a `CATEGORY:` field to every verdict (`correctness | security | logic | style | nitpick |
doc`). It feeds the gating in Change 4 and the existing skepticism-for-nitpicks behavior.

New verdict shape (analysis subagent, Phase 4):

```
VERDICT: agree_obvious | <one-line fix>
CATEGORY: <correctness|security|logic|style|nitpick|doc>

VERDICT: agree_unclear | <2-3 options separated by " OR ">
CATEGORY: <...>

VERDICT: disagree
CLAIM: <the comment's specific claim, restated>
EVIDENCE: <file:line + exact snippet that makes THAT claim moot, or why the suggestion is worse>
CATEGORY: <...>

VERDICT: outdated_fixed
CLAIM: <the comment's specific claim, restated>
EVIDENCE: <file:line + current code that already fixes it>
CATEGORY: <...>
```

### Change 3 — Fix the class, not the instance (Phase 5.1 generalize pass)

After the user accepts fixes and **before apply**, add a generalize pass. For each accepted
finding, a sonnet subagent searches the codebase (`grep` on the pattern) for siblings — other
event types, call sites, inputs, files that share the same defect. It returns a `category`
name and a list of sibling sites (`file:line`).

Because generalizing widens the blast radius (touching more than the comment literally asked),
the expanded scope is shown to the user before applying:

```
U1 (add contents: read) generalizes to a category: 3 sites
  - .github/workflows/a.yml:12
  - .github/workflows/b.yml:8
  - .github/workflows/c.yml:20
Apply to: all / original only / select
```

The apply subagent (5.2) fixes the confirmed sites; the reply names the category.

### Change 4 — Pre-push adversarial self-review (new Phase 5.3)

A fresh skeptic pass between apply and reply.

- **Gating (by verdict nature):** run only if at least one accepted finding has
  `CATEGORY ∈ {correctness, logic, security}`. Skip pure style/nitpick/doc rounds.
- **Skeptic:** one fresh sonnet subagent over the applied diff (`git diff`) plus the list of
  findings it was meant to close. For each finding it answers: is it fully closed? did the fix
  shift the problem to an adjacent case? what would the next review round flag (including
  siblings missed by Change 3)?
- **Output (surface → mini-confirm):** material findings are shown as an addendum batch,
  reusing the Phase 5.1 confirmation machinery; the user confirms, accepted items are applied,
  then the flow proceeds. If nothing material is found, continue silently.
- **Bounds:** a single pass — no loop. Cost is one extra subagent per code-touching round.
- **Order:** sits at 5.3, ahead of the 5.4 reply, so replies on the platform describe the
  final code.

### Phase 5 renumbering

```
5.1 Batch confirmation  (+ generalize pass, Change 3)
5.2 Apply changes
5.3 Pre-push adversarial self-review   (NEW, Change 4)
5.4 Reply on the platform              (was 5.3)
5.5 Commit                             (was 5.4)
5.6 Push                               (was 5.5)
5.7 Summary report                     (was 5.6)
```

### Supporting edits (consistency across the skill)

- **Quick Reference** table — reflect the new self-review step and generalize pass.
- **Scope Boundaries** — add "generalize accepted fixes to their class" and "adversarial
  pre-push self-review" to *This Skill DOES*.
- **Red Flags** — add: "dismissing without citing the exact moot code", "fixing only the
  instance when it's one of a class", "pushing a code/logic round without the self-review".
- **Common Rationalizations** — matching rows.
- **Examples** — update the GOOD example to show the new verdict format (CLAIM/EVIDENCE), the
  generalize confirmation, and a self-review round.
- **Phase 4 display** — group verdicts using the new structured fields.

## Testing & validation

Prompt-only skill; no automated tests. Validate via `superpowers:writing-skills` (frontmatter
+ structure checks) and a dry-run walkthrough: mentally replay the PR #89 scenario against the
edited skill and confirm each root cause is now caught —

1. A shallow "already handled" dismissal is blocked because EVIDENCE can't cite code that
   moots the specific claim → verdict flips to `agree`.
2. The head-SHA cutoff is fixed as a class (generalize pass enumerates all event types) rather
   than one at a time.
3. The self-review catches a fix that shifted the defect to the adjacent case before the push.

## Risks

- **Cost/latency.** sonnet on every comment + a generalize subagent per accepted finding + one
  skeptic subagent. Bounded: generalize only on accepted findings, skeptic only on
  code/logic/security rounds, single skeptic pass.
- **Over-generalizing.** The user confirms the expanded scope (all / original / select) before
  any sibling is touched, so widening never happens silently.
- **Extra confirmations.** The self-review mini-confirm appears only when the skeptic finds
  something material; clean rounds stay silent.
