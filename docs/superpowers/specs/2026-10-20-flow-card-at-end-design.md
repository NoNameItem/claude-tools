# flow:start / flow:continue — the task card is the last thing the skill shows

**Task:** claude-tools-elf.49
**Date:** 2026-10-20
**Status:** implemented (flow:start Step 9; flow:continue behaviour unchanged — §4 — one allowed-tools grant added for the contract parser)

Mockups: none — the output is terminal text, and the card itself is the existing `flow-task-card`
rendering, unchanged.

## Problem

The card answers one question for the user (their words, 2026-10-20): "рассказать мне над какой
задачей я сейчас работаю и что мы хотели сделать в этой задаче". It is orientation at the moment
work begins, so it belongs at the end of the skill run, where the user starts working.

**`flow:start` shows it in the middle.** Step 3 renders the card right after task selection, before
the branch question, the status update, the branch/worktree creation, `flow:init-worktree`, the
`Git:` link and the syncs. Observed on 2026-10-20 while starting this very task: card → branch
question → worktree → an init confirmation turn → `uv sync` → `Git:` link, and the skill's final
message was a bulleted recap with the card several screens up.

**`flow:continue` already ends on the card** (Step 9, "This is the final output"), and no concrete
failure of it was ever recorded: the task was created on 2026-07-22 from a one-line request
("карточки задач должны отображаться в конце работы скиллов flow:start и flow:continue"), and the
"not guaranteed to be the last visible block" wording in the task was the agent's. The real risk
is the one this session demonstrated in `flow:start`: the general pull to close a turn with a
summary. "This is the final output" says what the card is, not that nothing may follow it.

## Decision

1. **Both skills end with the full card**, verbatim, in a fenced block, as the last thing in the
   skill's final reply. Nothing follows the closing fence. One-line results of the run
   ("Назначил задачу на вас.", "Переключился в worktree …") go above the card; there is no recap
   after it.

   **Scope — the skill's output, not the whole turn** (the user's choice, 2026-10-20). Either skill
   can run inside a broader request ("продолжаем elf.49, пиши план", or `/flow:start` with more
   text after it). Then the card closes the skill's part, and the work the user asked for beyond
   the skill may follow it in the same turn. What may never follow the card is a recap of what the
   skill did. With no further request, the card ends the reply.
2. **`flow:start` no longer shows the card in Step 3.** The user's words (2026-07-22): "в середине
   flow:start это врядли нужно". Trade-off, confirmed in the 2026-10-20 brainstorm: the user picks
   the branch strategy without the full description in front of them; they have seen the ID,
   title, type and priority in the tree they picked from.
3. **The Step 6 branch question names the task by ID and title**, since no card precedes it any
   more.
4. **Early exits show no card** — no work starts. `flow:start`: no tasks, takeover declined
   (Step 7c "no"). `flow:continue`: no tasks, `new`, task not found / not `in_progress`, no `Git:`
   line, branch not found. `new` in `flow:start` is **not** an exit: it launches `bd create`
   (`2026-01-18-flow-start-task-display-design.md`) and Step 2 maps the selection to a task ID and
   proceeds, so the created task ends on the card like any other path.

## Non-goals

- No change to `flow-task-card` (format, width, content).
- No shortened card or one-line preview in the middle of `flow:start`.
- No change to which steps run or in what order, apart from where the card is rendered.
- No renumbering of `flow:start` steps.
- No change to other skills (`flow:done`, `flow:decompose`, …).

## Design

### 1. `flow:start` Step 3 — a silent read instead of the card

`### 3. Show Task Description FIRST` becomes `### 3. Read the Task`: run `bd show <task-id> --json`
once and keep the JSON; do not render a card here. The JSON feeds:

- Step 6 — the task title for the branch question;
- Step 7 — the `assignee` field (reuse it instead of the re-fetch Step 7 does today, the way
  `flow:continue` Step 4 says "this JSON is reused in Step 5");
- Step 8.1 — the existing `Git:` lines that decide whether to ask for a label.

Why keep the step rather than delete it: the other step numbers and their many cross-references
(5.5 "skip to Step 7", "Step 7.2", the examples) stay valid, and the `AGENTS.md` principle
"Analyze before acting" ("skills read full context (task card, branches, PR state) first") stays
true — the agent still reads the task before acting; only the user-facing display moves.

Cross-references to repoint:

- Step 2 (line 177): "proceed to Step 3 (Show Task Description)" → "(Read the Task)".
- Step 7 (line 312): drop "Step 3 piped the JSON into `flow-task-card`, which does not show
  assignee — fetch it here"; read `assignee` from the Step 3 JSON. `flow-actor` stays.
- Step 8.1 (line 419): "The task description (from Step 3 / the task card)" → "(from the Step 3
  JSON)".

### 2. `flow:start` Step 6 — the question names the task

Every Step 6 template's first line carries the task title next to the ID (e.g.
`Как продолжить работу с веткой для задачи {task-id} «{title}»?`). Exact wording is the builder's.

### 3. `flow:start` — a new final Step 9 "Show Task Card"

After Step 8.1, on every path that reaches it: create here, create in worktree, checkout existing
(here / worktree), stay on the current branch, and both Step 5.5 auto-resolve cases. It fetches
fresh — `bd show <task-id> --json | flow-task-card` — because the status (`in_progress`) and the
`Git:` line changed after Step 3. It closes with `flow:continue` Step 9's text verbatim (§4): the PR #74 paragraph and
"This is the final output…". The Quick Reference table gets a matching row; row 3 becomes the read.

### 4. Final-step wording — no new rule

**RED baseline, 2026-10-20** (`superpowers:writing-skills`; sonnet, one fresh subagent per reply,
the `flow:continue` text at `53d6b5b` as the no-guidance control): 10 replies, **0 recaps after the
card**. Scenario 2 (heavy service output, "the user stepped away"): 5/5 one-line result → card,
reply ends on the card. Scenario 3 ("continue elf.49 and draft a three-step plan"): 5/5 put the
requested outline **above** the card and end on the card. One run had read the plan through the
card's `Design:`/`Plan:` lines; the fixtures were stripped and that run repeated, same result.

The control does not exhibit the failure, so per `writing-skills` there is nothing to fix and no
wording is authored. `flow:continue` Step 9 — the PR #74 verbatim paragraph followed by "This is the
final output. The user sees it and starts working." — already produces Decision 1, and the user
approved proceeding without a rule (2026-10-20). With a broader request the requested work lands
above the card rather than after it; that meets the Acceptance (card last, no recap).

`flow:start`'s new Step 9 closes with that same text, verbatim. Its scenario 1 GREEN run doubles as
the control for a rule: if replies there append a recap after the card (`flow:start` prints more
service output than `flow:continue`), that is a real baseline, and a final-reply recipe (the parts
in order, not a prohibition list — writing-skills "Match the Form to the Failure") is authored in
both skills with scenarios 2–3 re-run.

*(Changed after approval, twice on 2026-10-20: first from a prohibition rule to a recipe when
`writing-skills` was applied, then to no rule after the RED baseline.)*

### 5. `flow:start` — text that now says the opposite

| Line | Today | Change |
|---|---|---|
| 35 | Overview: "Users choose tasks, see context first, and decide on branch strategy" | Drop "see context first"; say the run ends on the card |
| 77 | Quick Reference row 3: "Context BEFORE commitment, reproduce in reply" | Row 3 = read JSON, no card; new row 9 = card, final output, last block |
| 179–189 | Step 3 body, "**User needs context BEFORE committing to task.**" | Replaced by §1 |
| 456 | Red Flag "Description can go in summary at the end" | Remove — it now contradicts the design |
| 514 | BAD example problem "Description shown after actions" | Remove that bullet |
| 534, 567, 600 | GOOD examples render the card before the branch question | Branch question first; the card closes the example |
| 615 | Edge case "Still show full description via script" | The final card (Step 9) is shown as on any other path |
| 668 | Bottom Line "Show context first, let users choose, …, then act" | Reword: let users choose, recommend, act — then end on the card |

### 6. `flow:continue`

No change (§4: the RED baseline shows it already ends on the card). The §8 contracts guard it.

### 7. Docs

- `plugins/flow/README.md`, the `/flow:start` blurb: "displays full task details, then handles
  branch creation or checkout" → handles branch creation or checkout (worktree optional) and ends
  with the full task card.
- `plugins/flow/AGENTS.md`, principle "Reproduce the card inline": add that the card is the last
  block of the skill's final reply.

### 8. Contracts — `plugins/flow/bin/tests/test_flow_skill_contracts.py`

- `start`: the Step 3 section does not invoke `flow-task-card`; every `flow-task-card` invocation
  in the workflow lies in the last workflow step (`### 9.`).
- `start` and `continue`: the last step renders the card and says "This is the final output"; no
  `flow-task-card` anywhere earlier in the workflow; the text from "After running the script" to
  the end of the step is identical in both skills.
- `start`: the last step names Step 5.5 and "the reply that finishes the skill"; every Step 6
  template's first line carries `{title}`; the stale "context first" phrases are gone.
- README `/flow:start` blurb and the `AGENTS.md` principle say the card comes last.

## Constraints on implementation

- Skill edits go through `superpowers:writing-skills` (repo CLAUDE.md): RED baseline on the
  current text → GREEN → REFACTOR, wording micro-tests with 5+ reps per variant against a
  no-guidance control, every reply read by hand, then the full pressure scenarios. If the control
  does not show the failure, there is nothing to fix: no wording is authored for that skill, and
  the deviation from this spec goes back to the user before the task continues (it did — §4).
  Baseline for `flow:start`: this session's run, which ended on a recap.
  For `flow:continue`: a run with a lot of service output (worktree creation + init) before Step 9
  and an invitation to "summarise what happened". A third scenario covers the scope exception: the
  skill invoked inside a broader request ("continue elf.49 and write the plan") — the requested
  work may follow the card, a recap of the skill's actions may not.
- `/flow:*` executes from the installed 3.1.0 cache, so the change cannot be dogfooded on this
  branch; verification is the contracts plus the pressure runs.
- `SKILL.md` texts are under contract tests: run `uv run pytest` (via a haiku subagent) before the
  first commit, not after CI. The test file is Python: `ruff format`/`ruff check --fix` on it,
  `uv run ty check` pathless.

## Acceptance

- `flow:start` renders no card before the branch question; Step 3 only reads the task JSON.
- The `flow:start` branch question names the task by ID and title.
- On every successful `flow:start` path listed in §3, the final reply ends with the full card in a
  fenced block and nothing after it.
- `flow:continue`'s final reply ends with the full card and nothing after it — already true (§4).
- When either skill runs inside a broader request, no recap of the skill's actions follows the card.
- Early exits (Decision 4) show no card.
- README and `AGENTS.md` updated as in §7.
- The §8 contracts exist and `uv run pytest` is green; scenario 1 GREEN: 5/5 replies end on the
  full card.

## Left to the builder

Exact wording of the Step 6 templates and the reworded overview/Bottom Line;
the shape of the contract helpers; the commit type for the PR.
