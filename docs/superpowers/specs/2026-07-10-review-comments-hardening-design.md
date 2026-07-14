# Review-comments skill hardening — design

**Task:** claude-tools-elf.26 (review-comments inline context — PR #109 review round)
**Date:** 2026-07-10
**Status:** approved, pending implementation plan

## Context

The `flow:review-comments` skill rework (elf.26) went through four waves of Codex
`review-gate` feedback on PR #109. Each wave largely re-flagged bugs introduced by the
*previous* wave's point-fixes:

| Wave | Findings | Commit(s) |
|------|----------|-----------|
| 1 | C1–C5 (5) | `5e4b6d2`, `b3e2085` |
| 2 | N1–N7 (7) | `ed63207` |
| 3 | M1–M6 (6) | `112de3d` |
| 4 | K1–K7 (7) | *this design* |

The waves do not converge because each round fixes the **instance** a reviewer observed,
not the **class** the instance belongs to. This design closes the classes instead. It is
the first application of the full brainstorm → plan → implement cycle proposed in
claude-tools-elf.30.

Wave-4 findings K1–K7 cluster into five root-cause classes, four of which have recurred:

| Class | Findings (incl. prior waves) | Root cause |
|-------|------------------------------|------------|
| A. Untrusted input reaches a shell | K1 (+ N1, M1) | recipes inline untrusted data into shell command source; each fix patches one site |
| B. Decision-override paths lack data | K4, K5, K6 (+ M5) | the model treats `verdict.suggested` as the outcome and hard-binds reply text to verdict fields; user overrides create (verdict × decision) pairs the recipe never enumerates |
| C. `(summary)` items | K2 (+ M2) | summaries are forced into the inline-thread data model and have no stable id |
| D. Snippet reconstruction edges | K3 (+ M3, M4, N3) | range arithmetic is specified inline with ad-hoc guards |
| E. No-op commit gating | K7 (+ M6) | the gate uses a proxy signal (git working-tree state) instead of the authoritative one (what the apply phase actually changed) |

## Goal

Resolve K1–K7 so that they and their prior-wave relatives cannot reappear. **Hybrid
scope**: close classes **A** and **B** structurally (they produced the most waves); fix
**C**, **D**, **E** with targeted edits that each state one clear invariant.

Non-goals (YAGNI):
- No changes to skill sections unrelated to A–E.
- No `--deep` mode / auto-escalation between apply-only and full-cycle handling — that is
  the separate question tracked in elf.30; this design only hardens the current skill.
- No thread resolve/merge behaviour (out of the skill's scope by definition).

## Class A — Untrusted data handling (structural)

**One convention, stated once**, cross-referenced by every site that touches untrusted data
(reviewer file paths, `bd create --title`/`--description`, reply bodies, the LLM `thought`):

> Untrusted data is **never inlined into shell command source**. Either (a) it never
> touches a shell — read files with the **Read tool**, pass JSON via `--argjson`/`jq`; or
> (b) it is materialized into a shell variable via a quoted heredoc and referenced as
> `"$var"`. Double-quoting an **inlined literal** is insufficient: quotes suppress word
> splitting and globbing but **not** command substitution `$(...)` / backticks.

Rationale: the danger is *inlining a literal*, not *missing quotes*. `"$path"` (a quoted
variable reference) is safe because the shell does not re-scan an expanded value for
`$(...)`; `"x$(touch).py"` (a quoted literal placeholder the agent fills in) is not, because
the substitution sits in the command text. N1 added quotes to the `sed` path and stopped
splitting/globbing but not `$(…)`; K1 is that residual.

**Concrete change for K1 (GitLab snippet reconstruction path):** mandate the **Read tool**
for reading the file at an untrusted path and **remove the `sed` fallback entirely**. The
Read tool passes the path as a structured argument that no shell parses, so the whole class
(splitting, globbing, command substitution, variable expansion) is eliminated — there is
nothing left for a fifth wave to re-open. The existing "prefer the Read tool" wording
becomes "use the Read tool; do not build a shell command from the path."

Existing sites already following the convention (`bd create` heredoc for title+description
from M1, `--argjson`/`jq` card assembly, reply-body heredocs) are re-pointed at the single
convention section rather than restating the rule.

## Class B — Decision model (structural)

Separate three things the skill currently conflates:

1. **Verdict** — the analysis output (`agree_obvious` / `agree_unclear` / `disagree` /
   `outdated_fixed`, plus `thought`, and any action/options).
2. **Decision** — the user's per-card choice: `fix` / `won't-fix` / `follow-up` / `skip`.
3. **Reply-text source** — which text becomes the posted reply.

State four **invariants** (principle-first, so cells nobody enumerated are still covered):

1. `fix` ⇒ there is always a concrete **action** to apply. Source by verdict:
   `agree_obvious` → the verdict one-liner; `agree_unclear` → the option the user picked;
   `disagree` → an **accept-anyway action collected at triage** (a `disagree` has no action
   of its own). [closes M5, keeps the disagree→fix path]
2. `won't-fix` ⇒ there is a **rejection reason**. The card's `thought` may be reused as that
   reason **only when the verdict was `disagree`** (there the thought is already anti-fix).
   For any other verdict overridden to `won't-fix`, ask for an explicit reason — the
   pro-fix `thought` must not become `"Won't fix: real crash; fix is obvious"`. [closes K6]
3. `skip` ⇒ a **first-class outcome**: no apply, no reply, recorded as skipped. An
   `agree_unclear` where the user picks "skip" is recorded as `skip`, not `fix`. [closes K4]
4. `follow-up` ⇒ a **task-id must exist** before Phase 5.5 posts "Filed as follow-up:
   {task-id}". If the batch confirm (5.4) is answered `edit`/`no` and a ref gets no task,
   that ref is recorded as skipped and **no** follow-up reply is posted for it. [closes K5]

Collect the extra data (accept-anyway action, explicit won't-fix reason, chosen option)
**at triage time** in Phase 4, so Phase 5 has everything it needs. Add a compact table of
just the non-obvious / override cells; the invariants cover the rest.

The Phase 5.5 reply table changes so `won't-fix` reads "the recorded rejection reason (=
`thought` only when the verdict was `disagree`)" instead of "the card's `thought`".

## Class C — `(summary)` as a first-class id (targeted, K2)

M2 told Phase 2.3 to "re-read a GitHub summary body by its review id", but the Phase 2.1
INDEX schema carries only `comment_id: null` for a `(summary)` item and forbids heavy
fields — there is no review id to re-read by, and the working-set selection passes
`{ref ⇒ stable-id}` pairs where a summary has no stable id.

**Change:** give a GitHub `(summary)` INDEX item a review-derived stable id — a new
`summary_id` field set to the GitHub review id (e.g. the `id` of the review whose body
produced the summary). Phase 2.2 selects a summary ref by `summary_id`; Phase 2.3 carries
it forward keyed by that id and re-reads the full review body from the already-fetched
reviews response by `summary_id`. GitLab summaries are unaffected — they keep a real
`discussion_id`.

## Class D — Single reconstruction precondition (targeted, K3)

Replace the scattered range guards with one rule for GitLab snippet reconstruction:

> Compute `[start, end]` **only** from range endpoints that have a current-file line number
> (`new_line != null`). Prefer `line_range` (a multiline note) when **both**
> `line_range.start.new_line` and `line_range.end.new_line` are non-null; else fall back to
> the single-line `new_line`. If no endpoint yields a current-file line (outdated / old-side
> deleted lines) → `snippet = null` (degrade, do not compute). Then clamp `start = max(1,
> start)`.

This makes the null check precede the arithmetic (closes K3: `line_range` present but
endpoints null), keeps the M3 clamp, and preserves the existing degrade-to-null rule.

## Class E — Gate on the apply-set, not git state (targeted, K7)

M6 gated commit/push on `git status --porcelain` over the whole tree. With unrelated local
edits or untracked files present at session start, that proxy is non-empty even when the
triage produced only `won't-fix` / `follow-up` / `outdated_fixed` — so it proceeds to
commit/push with nothing to commit.

**Change:** the apply phase (5.1/5.2) already works on "specific files that were modified"
— record that set explicitly as `APPLIED_FILES`. Phase 5.6 gates on `APPLIED_FILES` being
**empty** (skip commit and push, go to the 5.8 summary) and stages exactly that set. This
uses the authoritative signal (what apply changed), covers K7 (unrelated pre-existing
changes) and keeps the earlier untracked-new-file case (a file created by an apply subagent
is in `APPLIED_FILES`).

## Finding → class coverage

| Class | Directly closes (wave 4) | Retroactively strengthens |
|-------|--------------------------|---------------------------|
| A | K1 | N1, M1 |
| B | K4, K5, K6 | M5 |
| C | K2 | M2 |
| D | K3 | M3, M4, N3 |
| E | K7 | M6 |

## Testing (writing-skills RED → GREEN)

The edit target is a prose skill (`plugins/flow/skills/review-comments/SKILL.md`), so each
class edit is validated as a documentation test: a concrete failing scenario the *current*
prose mishandles, then the edit, then a re-check. Representative RED scenarios:

- A: a GitLab MR file path `x$(touch /tmp/pwn).py` — current prose builds a `sed` command
  that would command-substitute; edited prose reads via Read tool, no shell.
- B: an `agree_obvious` card overridden to `won't-fix` — current prose posts the pro-fix
  `thought`; edited prose collects an explicit reason. Plus `agree_unclear`→skip and
  follow-up `edit`/`no`.
- C: a GitHub `(summary)` item in the working set — current index has no id to carry/re-read;
  edited index carries `summary_id`.
- D: a GitLab multiline note whose `line_range` endpoints have `new_line == null` — current
  arithmetic subtracts from null; edited precondition degrades to `snippet = null`.
- E: session with unrelated staged edits + a triage of only `won't-fix` — current guard
  proceeds to commit; edited guard sees empty `APPLIED_FILES` and skips.

After the edits, an independent dogfood-skeptic verifies consistency: no literal
`AskUserQuestion` under `plugins/flow/skills/` (CI greps for it), heading parity via a real
markdown renderer, fenced-code integrity (the file intentionally uses 4-backtick wrappers),
and that every cross-referenced phase number resolves.

## Out of scope / follow-ups

- The apply/analyze subagents are declared `subagent_type="Bash"`; Class A assumes they can
  call the Read tool (the skill already documents "prefer the Read tool" there). If that
  assumption is wrong, the fallback is the Class-A option (b) materialize-as-variable — noted
  here so the plan can verify tool availability before removing the `sed` path.
- Broader mode selection (apply-only vs full-cycle) remains elf.30.
