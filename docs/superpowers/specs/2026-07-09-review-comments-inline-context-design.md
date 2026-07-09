# Design: review-comments — show inline code context and triage per comment in the terminal

- **Task:** claude-tools-elf.26
- **Date:** 2026-07-09
- **Artifacts:**
  - `plugins/flow/skills/review-comments/SKILL.md` (prompt-only skill — reworked Phases 2–5)
  - `plugins/flow/bin/flow-comment-card` (**new** rendering helper, with tests)

## Problem

`flow:review-comments` presents review feedback too thinly to act on it without leaving the
terminal:

- **Phase 2 collection** returns a terse TABLE (comment brief truncated to ~40 chars) plus a
  METADATA JSON whose `body` is truncated to ~200 chars and which carries **no code** — only
  `path` and line numbers.
- **Phase 4 analysis** is where the code is actually read, but that happens **inside a sonnet
  subagent**; the snippet never reaches the main context or the user.
- **Phase 4/5 verdicts** are shown grouped by type, again without the code and often without the
  full comment text.

Net effect: to understand *what a comment is even about*, the user opens the GitHub/GitLab web
UI. And because the pre-analysis TABLE is the only thing visible at selection time, the user
cannot make the decision that actually matters — **is this a real fix, a nitpick to dismiss, or
something big enough to defer to a follow-up?** — from the terminal.

## Goal

Make each review comment reviewable and triageable entirely in Claude Code. For every comment,
show, in the terminal:

1. the **code the comment is anchored to** (syntax-highlighted, GitHub/GitLab-UI style),
2. the **full comment text** and its reply thread,
3. the **agent's assessment** (category + a short honest take),

then let the user decide **fix / won't-fix / follow-up** per comment. Definition of done (from
the task): for each comment, file, lines, relevant code, and full text are visible without
opening the web UI.

## Non-goals

- **Resolving/dismissing threads** — the skill stays reply-only, as today.
- **ASCII-box card** (à la `flow-task-card`) — deliberately rejected; see Decision 5.
- **Rendering via ANSI colorizers** (`bat`/`delta`/`pygmentize`) — rejected in favor of markdown
  fenced blocks, which Claude Code highlights natively without piping ANSI through subagents and
  verbatim reproduction. `bat`/`delta` are also not installed here.
- **Changing the analysis rigor** — CLAIM + EVIDENCE for every dismissal stays exactly as today.
- **Committed tests for the SKILL prose** — the skill is a prompt, validated via
  `superpowers:writing-skills` RED→GREEN; only `flow-comment-card` gets committed unit tests.

## Decisions (resolved during brainstorming)

1. **Placement.** The rich per-comment card is the **decision surface**. The old pre-analysis
   "process all? yes/select/no" gate is removed for normal PRs.
2. **Analysis depth.** Analyze **all** non-`already_replied` comments up front (parallel sonnet),
   so the take shown at triage is a real, code-backed assessment — not a cheap guess (a take
   without reading code is exactly the shallow-dismissal failure the skill fights).
3. **Follow-up outcome.** Full support: triage yields **fix / won't-fix / follow-up**, and
   follow-up **creates a beads task** and replies in the thread.
4. **Code source.** `diff_hunk` is primary (what the reviewer saw; works for outdated; no file
   read). Current-file context is added for non-outdated comments when the hunk is thin.
5. **Render format.** **Markdown sections with fenced code blocks** — the only way to get real
   syntax highlighting and `+/-` diff coloring in Claude Code. An ASCII box cannot contain
   highlighted code.
6. **Triage semantics.** Three outcomes, **every comment gets a reply**: fix → `"Fixed: …"`,
   won't-fix → `"Won't fix: …"`, follow-up → `"Filed as follow-up: {id}"`.
7. **Triage UX.** Cards are shown **one at a time**; the user decides on each before the next is
   shown. **Execution is batched at the end** (generalize → apply → self-review → reply → commit
   → push) to preserve fix-the-class, a single skeptic pass, and one commit/push.

## New flow shape

```
Phase 0  Detect platform            (unchanged)
Phase 1  Detect PR/MR + sync branch (unchanged)
Phase 2  Collect + capture snippet  (add diff_hunk / position; return full body)
Phase 3  Analyze ALL (parallel)     (drop pre-selection gate; large-PR cap only)
Phase 4  Card-by-card triage        (TOC agenda → per-card card + decision loop)
Phase 5  Batch act                  (generalize → apply → self-review → reply → commit → push)
```

## `flow-comment-card` helper

A new `plugins/flow/bin/flow-comment-card`, in the style of `flow-task-card` (Python 3, stdlib
only, reads JSON on stdin, prints to stdout). **Pure formatting**: it reads no files and calls
no APIs — the caller supplies every field. This keeps it deterministic and unit-testable.

### Input (one comment, JSON on stdin)

```json
{
  "ref": "C1",
  "source": "bot",
  "author": "coderabbitai",
  "path": "packages/statuskit/src/git.py",
  "start_line": null,
  "line": 42,
  "outdated": false,
  "body": "full comment text, untruncated",
  "thread": [{"user": "you", "body": "already handled?"}],
  "diff_hunk": "@@ -40,7 +40,7 @@ def branch_name(repo):\n-    return repo.head.name\n+    ...",
  "snippet": {"lang": "python", "text": "def branch_name(repo):\n    return repo.head.name"},
  "category": "correctness",
  "thought": "Agrees — real crash on detached HEAD; the fix is obvious.",
  "suggested": "fix"
}
```

- `diff_hunk` — preferred code block; rendered as a ` ```diff ` fence.
- `snippet` — optional current-file context (or the GitLab-reconstructed snippet); rendered as a
  ` ```{lang} ` fence. Shown when `diff_hunk` is absent or thin.
- Either may be absent (summary/general items) → the card has no code block.

### Output (markdown, printed directly — NOT wrapped in a fence)

```
### 🔴 C1 · correctness · packages/statuskit/src/git.py:42

> **@coderabbitai:** full comment text, untruncated
> ↳ **@you:** already handled?

​```diff
@@ -40,7 +40,7 @@ def branch_name(repo):
-    return repo.head.name
+    return repo.head.name if repo.head else "(detached)"
​```

**Thought:** Agrees — real crash on detached HEAD; the fix is obvious.
**Suggested:** fix
```

Rendering rules:

- **Header:** `### {emoji} {ref} · {category} · {path}:{lines}` plus ` ⚠️ outdated` when
  `outdated`. `lines` = `{start_line}-{line}` for a range, else `{line}`; `(summary)` items show
  `(summary)` with no line. Emoji by category: 🔴 correctness/security/logic, 🟡 style/nitpick,
  🔵 doc, ⚪ fallback (unknown/none).
- **Comment:** blockquote `> **@{author}:** {body}`; each thread reply on its own
  `> ↳ **@{user}:** {body}` line.
- **Code block:** `diff_hunk` as ` ```diff `; else `snippet` as ` ```{lang} `; else nothing.
- **Take:** `**Thought:**` line, then `**Suggested:**` line (`fix` | `won't-fix` | `follow-up`).

### The no-outer-fence caveat (must be explicit in the skill)

`flow-task-card` output is reproduced **inside** a ` ``` ` fence (so its box shows as monospace).
`flow-comment-card` is the **opposite**: its output *contains* ` ```diff ` fences and markdown, so
it must be emitted **directly into the reply, unwrapped** — wrapping it in an outer fence would
stop Claude Code from rendering the highlighting and the blockquotes. The SKILL must state this
loudly so the agent does not wrap it out of habit.

## Phase 2 — collect with code

Same single haiku subagent as today, with additions:

- **GitHub:** capture `diff_hunk` from the `pulls/{n}/comments` response (already fetched — no
  extra call) into METADATA. Return the **full** comment `body` (drop the ~200-char cap); the
  card shows it whole. The TOC table (below) keeps a truncated brief.
- **GitLab:** discussions carry no `diff_hunk`. Store `position` (`new_path`, `new_line`,
  `old_line`, `line_range`); the snippet is reconstructed at render time from the current file
  around `new_line` (via `sed`) as a `snippet` object. For outdated (`new_line == null`) show the
  `old_line` context from the MR diff if available, else no code block plus an "outdated" note.
- METADATA gains: `diff_hunk` (GitHub, may be null), `position` (GitLab), full `body`. Existing
  fields (`ref`, source, `path`, lines, `outdated`, `thread`, reply targets, `already_replied`)
  are unchanged.

Larger METADATA (full bodies + hunks) is inherent to the feature — showing full comments and
code is the point. The large-PR cap (Phase 3) bounds the worst case.

## Phase 3 — analyze all

The same per-comment/grouped sonnet analysis as today, but run over **all** non-`already_replied`
comments (the pre-selection gate is gone). The verdict schema gains two card fields:

- `category` (unchanged set: correctness | security | logic | style | nitpick | doc),
- `thought` — one short paragraph, the honest take shown on the card,
- `suggested` — `fix` | `won't-fix` | `follow-up` (the recommended triage outcome).

CLAIM + EVIDENCE discipline for `disagree`/`outdated_fixed` is unchanged. For non-outdated
comments the subagent also returns a `snippet` (current-file context) when the `diff_hunk` is
thin or absent.

**Large-PR cap:** if there are more than ~20 non-replied comments, keep a single pre-analysis
gate — show the TOC and ask (plain text) "N comments — analyze all, or select a subset?" — to
bound token cost. Below the threshold, analyze all silently.

## Phase 4 — card-by-card triage

1. **Agenda (TOC).** Print a compact table so the user sees the whole set first:
   `ref · source · path:lines · category · brief · ⚠️`.
2. **Loop, one card at a time** (humans first, bots second). For each comment:
   - assemble the card JSON (Phase 2 metadata + Phase 3 verdict) and pipe it through
     `flow-comment-card`; emit the output directly (unwrapped);
   - ask, in plain text, for the decision on **this** comment, defaulting to `suggested`:
     ```
     C1 → fix / won't-fix / follow-up?  (default: fix)
     ```
   - if the verdict is `agree_unclear`, present the 2–3 fix options inline here and let the user
     pick before moving on;
   - record the decision; show the next card.
3. Decisions are **collected, not executed** during the loop.

Plain-text prompts by design: a structured multiple-choice dialog auto-submits its preselected
option on the AFK idle timeout (claude-tools-6q4), and the `Validate (flow)` CI greps the skill
for the literal dialog-tool name. The skill describes these as plain-text prompts only.

## Phase 5 — batch execution

After the whole set is triaged, act once, grouped by outcome:

### fix
Existing pipeline, unchanged: **generalize** the accepted fixes to their class (5.1), **apply**
grouped by file (5.2), run the **adversarial self-review** on any correctness/logic/security
round (5.3), then reply `"Fixed: …"` / `"Fixed: …; applied across the class ({class}) at {N}
sites."` (5.4).

### won't-fix
Reply `"Won't fix: {reasoning}"`, drawn from the card's `thought`. (Multi-line/​special-char
bodies via the quoted-heredoc pattern already in the skill.)

### follow-up
For each follow-up comment, create a beads task, then reply `"Filed as follow-up: {task-id}"`.

- **Parent epic** inferred from the comment's path (repo convention):
  `packages/statuskit/` → `claude-tools-5dl`, `plugins/flow/` → `claude-tools-elf`,
  `.github/`·`docs/`·root → `claude-tools-5vg`. The user confirms/overrides.
- **Type:** `bug` for correctness/security/logic, else `task`.
- **Title:** concise, from the comment's substance. **Description:** PR/MR URL, `path:lines`, the
  reviewer's comment text, brief context. **Priority:** default P2.
- Confirm the follow-up batch in one plain-text prompt ("creating N follow-ups under {epics} …")
  before creating. After creation, `flow-sync push` to persist to the shared beads store.

### commit / push / summary
Commit by scope (5.5, single-package-commit rules); **push with a plain-text confirmation** (5.6,
never a structured dialog — AFK auto-push, claude-tools-6q4). Summary report (5.7) gains a line:
`Follow-ups created: {ref → task-id}`.

## Edge cases

- **Outdated:** `diff_hunk` is historical, so the card still shows it as ` ```diff ` with the
  ⚠️ marker and a "line moved/removed in current code" note. Analysis still runs — outdated ≠
  fixed (unchanged philosophy).
- **Summary / general (no position):** card has no code block — source + full text + thought
  only, header shows `(summary)`. GitHub summary items have no reply target (`comment_id ==
  null`) → recorded in the summary report, no reply. GitLab summary has a `discussion_id` → reply
  normally. Follow-up is still a valid outcome for a summary item.
- **Deleted file:** treat as outdated (no snippet); analysis may still recommend follow-up.
- **GitLab thin/absent snippet:** if the file read yields nothing usable, render the card without
  a code block and note the position — degrade, don't fail.

## allowed-tools

Audit and extend the skill front-matter (per the `2026-07-07-flow-allowed-tools-audit` pattern,
commit `2f2a48c`). The current front-matter has **no `sed`** and no beads/flow helpers. Add only
what the **main context** now invokes:

- `Bash(flow-comment-card:*)` — the new renderer (and its `$(…)` command-substitution form,
  per claude-tools-elf.27's convention),
- `Bash(bd:*)` — follow-up task creation,
- `Bash(flow-sync:*)` — persist created tasks.

GitLab snippet reconstruction (`sed` over the current file) runs **inside the analysis
subagent**, which has its own tool grant — so `sed` does **not** need to be added to the skill
front-matter. `gh`/`glab`/`git`/`jq` are already allowed.

## Testing & validation

- **`flow-comment-card`:** committed unit tests in `plugins/flow/bin/tests/`, fixtures covering:
  GitHub inline (with `diff_hunk`), GitLab inline (reconstructed `snippet`), outdated, summary
  (no code block), a multi-reply thread, a range vs single line, and each category's emoji/header.
  Assert exact markdown output.
- **SKILL.md:** prompt-only → validate via `superpowers:writing-skills` RED→GREEN. RED: a fake
  `gh` fixture with a comment carrying a `diff_hunk`; following the *current* prose, the code
  never surfaces to the card. GREEN: after the edit, the card shows the highlighted snippet, full
  text, thought, and a per-card triage prompt; execution is batched. A dogfood skeptic checks
  GitHub↔GitLab consistency and that the no-outer-fence rule is stated.
- **CI:** do not write the literal structured-dialog tool name anywhere in the skill (the
  `Validate (flow)` grep fails even on prohibitions — phrase everything as plain-text prompts).

## Risks

- **Context size.** Full bodies + hunks + all cards live in the main context. Bounded by the
  large-PR cap and by the fact that the cards are the intended output anyway.
- **Render ownership.** The card JSON is assembled in the main context by merging Phase 2 + Phase
  3 outputs; a field mismatch shows an incomplete card rather than crashing (the helper tolerates
  missing optional fields).
- **GitLab snippet fidelity.** Reconstructing from the current file can drift from what the
  reviewer saw; mitigated by showing the position and degrading to no-code-block when unsure.
- **More round-trips.** One-at-a-time triage adds interaction; deliberate — it is the point of
  the change, and the large-PR cap keeps it bounded.
