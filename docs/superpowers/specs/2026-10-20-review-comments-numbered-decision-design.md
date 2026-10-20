# flow:review-comments — the per-card decision is a numbered list

**Task:** claude-tools-elf.42
**Date:** 2026-10-20
**Status:** design

Mockups: none — the output is terminal text.

## Problem

Phase 4.2 asks for each card's decision as free text:

```
C1 → fix / won't-fix / follow-up?  (default: fix)
```

Every other choice in flow is a numbered list answered with a digit — `flow:start`, `flow:continue`,
`flow:review-loop`, and even the Phase 5.6 push prompt of this same skill. The mismatch makes the
user remember which prompt wants which format, and type `won't-fix` in full instead of one digit.

The `agree_unclear` case is worse: its 2-3 fix options are presented "inline" in prose, so picking
one takes either a prose answer or a second exchange.

## Decision

1. **The decision is a numbered list, `suggested` first.** The recommended item is first and marked
   `(recommended)`; the other two follow in the canonical order fix → won't-fix → follow-up. The
   digit for a given decision therefore varies between cards (on a `disagree` card `1` is
   won't-fix). Confirmed by the user on 2026-10-20: they read the number off the list in front of
   them.

   "First" means the card's **default**, which today is `suggested` except for one row: a GitHub
   review-body summary (`kind == "summary"` on `platform == "github"`) defaults to won't-fix
   whatever its verdict says (decision invariant 2). That rule stays, so for that row won't-fix is
   item `1` even when the card's `Suggested:` line says fix.
2. **`agree_unclear`: lettered options and a single answer.** The fix options are listed as A, B, C
   above the numbered list, and the user answers once with the digit Fix holds on this card plus a
   letter — `1 A`. The user's words (2026-10-20): "я отвечаю 1 A"; when Fix is not first, "я
   указываю номер, который соответствует fix".
3. **A digit, the word, or an empty answer** (= `suggested`) are all accepted, so anyone who already
   types words keeps working.
4. **Plain text, never a structured dialog** — a dialog auto-submits its preselected option on the
   AFK timeout (claude-tools-6q4). Unchanged from today.
5. **The skill does not fix the prompt language.** Its text is English; the agent asks in the
   language of the conversation. The user's words (2026-10-20): "пусть агент сам выбирает, на каком
   языке общаться".

## Prompt format

Ordinary card (`agree_obvious` / `outdated_fixed`, `suggested: fix`):

```
C1 → what to do?
1. fix (recommended)
2. won't-fix
3. follow-up
```

`disagree` card (`suggested: won't-fix`):

```
U2 → what to do?
1. won't-fix (recommended)
2. fix
3. follow-up
```

`agree_unclear` card (`suggested: fix`):

```
C3 → what to do?
Fix options:
A. move the detached-HEAD guard up into resolve_branch
B. make branch_name total (return "(detached)" on a detached HEAD)
1. fix (recommended)
2. won't-fix
3. follow-up
For fix, add the option letter: 1 A
```

An `agree_unclear` card may suggest `follow-up` (a large or risky change); then the list is
`1. follow-up (recommended) / 2. fix / 3. won't-fix`, the hint line reads `For fix, add
the option letter: 2 A`, and the user answers `2 B` to fix with option B. The hint always uses the digit Fix
holds on that card.

The skill text writes the prompt in English, like the rest of the skill; the agent asks in the
language it is already using with the user — the skill does not fix the language. The decision
words (`fix`, `won't-fix`, `follow-up`) stay as written in any language: they are also accepted
answers.

**Where the options come from:** the verdict's `options` array when present, otherwise the options
the `thought` describes, in their order. One array element is one option; an element that itself
joins alternatives with `OR` (Phase 3's example reads `"A OR B OR C"`) is split into separate
options. The agent letters them A, B, C and does not invent, merge or drop options. If only one
option can be read, the card is shown as an ordinary one (no letters) and that option is the fix
action; if none can be read, Fix is followed by a plain-text question for the concrete change, as
in accept-anyway.

## Reading the answer

The agent interprets the answer (no helper parses it):

| Answer | Meaning |
|---|---|
| `1`–`3` | the decision at that position on this card |
| `fix` / `won't-fix` / `follow-up` | that decision; case and obvious spellings (`wontfix`, `won't fix`, `follow up`) ignored |
| empty | `suggested` |
| `<digit or word> <letter>` | on an `agree_unclear` card: fix with that option; case and the space are ignored (`1A`, `1 a`, `fix B`) |

Re-ask cases:

- **Fix on an `agree_unclear` card without a letter** (including an empty answer when `suggested` is
  fix) → ask for the letter only, not the whole decision again. The verdict says the agent itself
  could not pick; silently taking A would turn that ambiguity into a decision nobody made.
- **A letter with won't-fix or follow-up, a letter that is not listed, a digit outside the list** →
  repeat the decision prompt (not the card).
- **Prose** ("fix A, and rename the helper too") → take the intent when the decision, and for
  `agree_unclear` the option, are unambiguous; otherwise repeat the prompt.

## What stays as it is

- `disagree` → fix (accept-anyway): after the user picks Fix's number, the existing plain-text
  question for the concrete change still follows.
- `agree_*` → won't-fix: the existing question for an explicit rejection reason still follows.
- The GitHub review-body summary row: its default is won't-fix (invariant 2), so won't-fix is item
  `1` and Enter or `1` still settles it "in one keystroke".
- What is recorded: the decision is still `fix` / `won't-fix` / `follow-up`. For `agree_unclear`
  the chosen option's **text** is recorded as the fix action (decision invariant 1), not its letter —
  letters only mean something on the card they were shown on.
- Phase 5, the ledger, replies.

## Changes

- `plugins/flow/skills/review-comments/SKILL.md`
  - Phase 4.2: the prompt block and the bullets under it (the "Empty / Enter" and `agree_unclear`
    bullets), the answer rules above, and the "including the `agree_unclear` fix options inline"
    wording in the two-part reply contract.
  - Examples: the prompts in "GOOD: Full workflow" (C1, U1, C2 — C2 is the `won't-fix`-first case)
    in the new format, with answers given as digits; plus a short new GOOD example of an
    `agree_unclear` card answered `1 A`.
- `plugins/flow/bin/tests/test_flow_skill_contracts.py`
  - `test_review_comments_triage_has_no_skip_outcome` asserts the old literal
    `fix / won't-fix / follow-up?` — update it to the new prompt.
  - Add contract tests for the new rules: numbered list with the recommended item first; digit,
    word and empty answer accepted; lettered options with a `<digit> <letter>` answer; the letter
    re-ask; the old prompt gone from Phase 4.2 and the Examples.

No change to `flow-comment-card` or any other helper: the card renders the `Suggested:` line and
does not render options.

## Non-goals

- Other prompts in this skill: the 5.4 follow-up batch (`yes / edit / no`), the won't-fix reason
  question, the accept-anyway question.
- The Phase 3 verdict schema and subagent prompt.
- Other flow skills.

## Acceptance

- Phase 4.2 describes the numbered list with the recommended item first.
- It says explicitly that a digit, the word and an empty answer are accepted.
- The `agree_unclear` handling uses the same list with lettered options and a single answer.
- The Examples use the new format.
- A full `uv run pytest` passes, including the updated and new contract tests.

`/flow:*` runs from the installed plugin release, not the worktree, so the new prompt can only be
seen in a real review round after the release; until then acceptance is the skill text plus the
contract tests.

## Left to the builder

- Exact wording of the SKILL.md text and of the contract-test assertions (follow the existing
  `section(...)` / regex style in `test_flow_skill_contracts.py`).
- Whether the answer rules are a table or bullets in SKILL.md.
- Skill edits go through `superpowers:writing-skills` (repo CLAUDE.md).

## Calls made by the designer (not discussed with the user)

- Recommended marker `(recommended)`, lowercase decision words kept untranslated whatever the
  conversation language.
- A hint line on `agree_unclear` cards only.
- Fix without a letter → re-ask the letter only; invalid combinations → repeat the prompt.
- Option text, not the letter, is recorded.
- One readable option → shown as an ordinary card; none → Fix asks for the change in plain text.
- An `options` element joined with `OR` is split into separate options.
- The GitHub summary row keeps its won't-fix default over the verdict's `suggested` (the existing
  invariant 2, carried over rather than re-decided).
- Prose answers interpreted for intent, otherwise re-asked.
