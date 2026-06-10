# Flow Card Step: Always Reproduce the Task Card Inline in the Reply

**Task:** claude-tools-elt
**Date:** 2026-06-10
**Status:** Design

## Problem

The "show task card" steps in `flow:start` (Step 3) and `flow:continue` (Step 8) run
`bd show <task-id> --json | flow-task-card` and leave the result as a raw Bash tool
output. The Claude Code UI collapses long tool results to a single line, so the user
sees only the card's first line — the description, links, and dependencies stay hidden.

The current skill instructions do not clearly require reproducing the card in the
assistant's reply:

- `plugins/flow/skills/start/SKILL.md:179` — "Output the script result in a ``` code
  block to preserve monospace alignment." Reads as a statement about the script's
  output format, not as a requirement to repeat it in the reply.
- `plugins/flow/skills/continue/SKILL.md:279` — "Output in a ``` code block to
  preserve alignment." Same ambiguity.

Agreed earlier (recorded in the task): the card stays full — `flow-task-card` is not
truncated. The instruction is what gets fixed.

Suppressing the tool output entirely is not possible: the model must receive the
script output to reproduce it, and tool results are always rendered (collapsed) by
the UI. The collapsed single line is acceptable; the authoritative copy of the card
lives in the reply.

## Solution

Fix the wording in both skills. The instruction is a positive imperative only — no
mention of tool output, UI collapsing, or Ctrl+O.

### 1. Card-step instruction (both skills, identical text)

Replace the ambiguous sentence in `start/SKILL.md` Step 3 (line 179) and
`continue/SKILL.md` Step 8 (line 279) with:

> After running the script, reproduce its **full output verbatim** inside a fenced
> ``` code block in your reply — **every line** from the top border `┌─` to the
> bottom border `└─`, none dropped. The card must appear in your message text — that
> is the only place the user reliably sees it. Do not summarize, truncate, or
> reformat it.

The "every line" clause was added after subagent testing: with the shorter wording,
one test run still silently dropped a single line (`Affects:`) from the middle of
the card while otherwise complying.

### 2. Red Flags (both skills)

Add to the Red Flags section:

> - "The card is already displayed" → It is not. The card is visible only if YOU
>   reproduced it verbatim in a code block in your reply.

### 3. Common Rationalizations (both skills)

Add a table row:

> | "Running the script is enough to show the card" | No. Reproduce the script output verbatim in a fenced code block in your reply. |

### 4. Consistency pass

- Quick Reference tables: append "reproduce in reply" to the Key Point of `start`
  Step 3 and `continue` Step 8.
- Examples in both skills already show the card inside the agent's reply; verify
  they do not contradict the new wording and adjust if needed.

## Scope

Only `plugins/flow/skills/start/SKILL.md` and `plugins/flow/skills/continue/SKILL.md`.
The `flow-task-card` script is untouched.

Out of scope: removing the untracked leftover directory
`plugins/flow/skills/starting-task/` (empty remains after the skill rename).

## Testing

Manual: run `/flow:continue` (or `/flow:start`) and confirm the card is reproduced
verbatim in the assistant's reply inside a fenced code block. The repository has no
automated tests for skill prose.
