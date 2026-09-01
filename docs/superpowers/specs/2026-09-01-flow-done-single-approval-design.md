# flow:done — one scenario, one approval

**Task:** claude-tools-elf.59
**Date:** 2026-09-01
**Status:** approved, pending implementation plan

## Problem

`flow:done` stops and asks at every step. A single ordinary run (closing `claude-tools-5vg.8`,
2026-08-28) collected three consecutive `yes` answers, none of which had a realistic alternative.

The deeper issue is not the count but the shape: the skill asks *while* it works, so each question
sees only its own local state. It cannot say what the whole run will do, and the user cannot answer
once for all of it. Mechanical agreement to a series of such questions also devalues the
confirmations that do carry a choice.

### Full inventory of confirmation points (SKILL.md, current)

| # | Location | Question | Fires when | Typical run |
|---|---|---|---|---|
| 1 | Step 1, l. 66–79 | "PR exists: {url} (state: {state}). Proceed to close task on this branch?" | feature branch + PR exists — **any state** | always |
| 2 | Step 2, l. 92 / 712 | "Which task is complete?" | more than one in_progress leaf | never in practice (see below) |
| 3 | Step 4.1, l. 137 / 741 | "Which file is the implementation plan?" | several plan candidates | rare |
| 4 | Step 4.2, l. 143–152 | "Plan file found. Delete / Archive / Keep" | plan found | when a plan exists |
| 5 | Steps 5–6, l. 180–230 | "Parent {id} now has all children closed. Close it too?" | parent has no open children — **recursively** | 0–N times |
| 6 | Step 8.3, l. 262–278 | "Delete branch and associated resources?" | branch matches task | always |
| 7 | Step 8.4 item 8, l. 300–308 | "PR #{n} is CLOSED... Delete the ledger?" | `PR_STATE=CLOSED` + ledger exists | rare |
| 8 | Step 8.4 error / l. 810 | "Force-delete with `git branch -D`?" | `git branch -d` refused — **always under squash merge** | always |

Not confirmations: "feature branch without PR" is a hard exit, and a failed `git worktree remove`
is a message that does not block.

**Ritual:** #1 in the `MERGED` state and #8. Both are decided by state known in advance — the work
is already in master, and `-d` is guaranteed to refuse under squash merge (CONTRIBUTING.md,
"Merge Strategy"). **Real choices:** #2, #3, #5, #7. **#4** has three options but one habitual
answer.

### Three findings the task description does not mention

**F1. Step 1 asks before the task is known.** The branch check runs at step 1; the task is only
found at step 2. So "Proceed to close task on this branch?" is asked without a task id, and
direction A of the task ("do not ask when the PR is MERGED *and* the branch matches the task being
closed, via `flow-current-task`") is not expressible in the current step order — that helper needs
the id.

**F2. Questions #2 and #3 never fire.** Step 2 is a bare `bd list --status=in_progress` plus the
prose instruction "Filter for leaf tasks", left to the model's judgement; the `flow-find-leaf`
helper that exists for exactly this is used only by `flow:continue`, which additionally resolves
the task deterministically from the `Git:` lines. In practice the model takes the task it has been
working on and asks nothing — which happens to be right, but is not reproducible, and would behave
differently after a `/clear`. This is the class of defect tracked as `claude-tools-elf.35`.

**F3. "Is there a PR" is the wrong signal for "is the work done".** The skill treats `gh pr view`
as the single source of truth. In a repository with **no remotes at all** (the user has one) `gh`
returns nothing, the skill reads `NO_PR` and exits to `superpowers:finishing-a-development-branch`
on every run — `flow:done` is unusable there by construction. The same false exit occurs on GitLab
repositories, where the MR exists but `gh` cannot see it (`claude-tools-elf.50`).

### Evidence: how to detect "merged" without a platform

`git branch --merged` and `git merge-base --is-ancestor` both report false after a squash merge,
which is this repository's only merge strategy. The reliable test is whether the branch still adds
anything to the base:

```bash
git merge-tree --write-tree <base> <branch>   # == git rev-parse <base>^{tree}  →  merged
```

Verified on git 2.47 against two models built with plumbing (2026-09-01):

| Model | merge-tree result | base tree | Verdict |
|---|---|---|---|
| squash merge: commit carrying `164558c`'s tree, different SHA, parent `master~1` | `93e260e1` | `93e260e1` | merged ✓ |
| unmerged: commit adding a new file on top of `master` | `0b3fafd6` | `93e260e1` | not merged ✓ |

It works with and without a remote, and survives squash and rebase.

`--write-tree` requires git >= 2.38. On an older git the criterion is unavailable: the skill
says so, prints the branch and base it could not compare, and asks the user to confirm the work
is merged before building the scenario. **The answer is defined in both directions.** "Yes" leaves
mergedness **unconfirmed**: it permits closing the task, closing eligible parents, handling the
plan and running `flow-sync push` — none of which destroys anything — but never counts as the
check, so every branch, worktree and remote deletion goes to "Не буду" with that reason. "No" (or
any non-affirmative answer) behaves exactly like a failed safety check: report and exit, nothing
closed, deleted or synced. It does not silently fall back to `git branch --merged`, which is wrong
under squash merge precisely when it matters.

The same "unconfirmed" verdict covers a second case the tree comparison alone cannot see: a branch
that carries **no commits of its own** (`git rev-list --count <base>..<branch>` == 0) also satisfies
`merge-tree == base^{tree}` — a `flow:start` branch whose work was never committed looks exactly
like a merged one. That is not merged: the run continues (close, parents, plan, sync) but refuses
every deletion, because the worktree may hold the only copy of the work.

## Design

### D1. Flow structure

Steps 1–8 are replaced by six:

| Step | Does | Stops? |
|---|---|---|
| 0 | `flow-require-bd` — unchanged | no |
| 1 | **Collect state** — branch, repository mode, task, mergedness, parents, plan, worktree, ledger | no |
| 2 | **Safety check** — work not merged into the base branch: report, suggest `superpowers:finishing-a-development-branch`, exit | exit |
| 3 | **Scenario** — print everything that will be done, ask the single question | yes, once |
| 4 | **Handle the answer** — approval → step 5; correction → rebuild scenario, back to step 3 | loop |
| 5 | **Execute** — fixed order, report per item | no |
| 6 | **Summary** — what was done, what failed | no |

Every confirmation that used to interrupt the run — parent closing, the plan's fate, branch and
worktree deletion, the ledger, `-D` under squash — becomes a line of the scenario with a default.

The safety check of step 2 is kept deliberately: it is not ritual. Only its criterion changes, from
"a PR exists" to "the work reached the base branch" (F3).

### D2. State collection (step 1)

Collected in one pass and without questions; the only external effect is the `git fetch` of
D2.1, which updates remote-tracking refs and nothing else:

| Fact | How |
|---|---|
| Current branch | `git branch --show-current` |
| Repository mode | `git remote` — empty → local-only, else remote mode |
| Base branch | first that resolves: `git symbolic-ref --quiet refs/remotes/<remote>/HEAD`, then `<remote>/master`, then `<remote>/main`; local-only: first existing of local `master`, `main`. Yields two values — `BASE_REF` (`origin/master`, the comparison base) and `BASE_LOCAL` (`master`, the checkout target). None resolves → the run stops (D2.4) |
| **Mergedness** | `git merge-tree --write-tree <base> <branch>` == `git rev-parse <base>^{tree}` |
| PR state | `gh pr view --json state,url,number` — remote mode only |
| Task | session context → branch → `flow-find-leaf` |
| Parent chain | `bd show` upwards: id, type (`epic` or not), open-children count |
| Plan file | `Plan:` line in the description, else `git ls-files --others --modified` over the plan directories |
| Worktree | `flow-in-worktree` |
| Remote branch | `git branch -r` |
| Ledger | present when a `PR_NUMBER` was obtained |

Three decisions differ from today's behaviour:

**D2.1. The base comes from the remote, not from the local ref.** Comparing against a local
`master` that lags (no `git pull` since the PR merged) makes the criterion report "not merged" and
the safety check evict the user for no reason. In remote mode: `git fetch` first, base is
`<remote>/<default>`. In local-only mode the local branch is the only option.

`git symbolic-ref refs/remotes/origin/HEAD` is only the **first candidate**: that ref is frequently
absent or not a symbolic ref (this repository: `fatal: ref refs/remotes/origin/HEAD is not a
symbolic ref`), and the remote is not always named `origin` — hence the `git remote` lookup and the
`master` → `main` fallback chain. **If nothing resolves, the run stops** (D2.4); an empty base makes
`merge-tree` error out, and that comparison is what guards every deletion.

Comparison base and checkout target are kept as separate values. `BASE_REF` (`origin/master`) goes
to `merge-tree`, `rev-parse` and `rev-list`; `BASE_LOCAL` (`master`) is what step 5 checks out —
`git checkout origin/master` detaches HEAD and the `git pull` after it fails with "You are not
currently on a branch".

**D2.2. Mergedness comes from git; the PR only supplements it.** `merge-tree` works in both modes
and survives squash. The PR state is needed solely to decide about the remote branch and the
ledger. Side effect: the skill becomes usable in a repository without remotes (F3).

**D2.3. `gh` is not invoked in local-only mode.** Today it always runs and its empty answer is read
as "no PR", i.e. as grounds for exit. Now the absence of a platform simply means the scenario has
no PR-related lines.

**D2.4. No base branch is a stop, not an improvisation.** When neither the HEAD symref nor
`master`/`main` resolves, the skill says which candidates it tried, changes nothing, and asks the
user to name the base. Guessing one would silently re-point the criterion that gates every
deletion.

**D2.5. Parent open-children counts are taken as of the moment they will be acted on.** The chain is
collected in step 1, but the task closes in step 5.1 and parents at 5.2 — so a count excludes the
task being closed and every lower ancestor the same scenario lists for closing. Read literally
(count the task as open), a container parent whose last open child is the task being closed could
never qualify and the row would be dead; read loosely, the rule would be unstated. Step 5 re-reads
`bd show <parent>` immediately before closing it, so the promise and the action see the same
state.

**Task resolution order** (F1, F2): the session context first — `flow:done` normally follows
`flow:start`/`flow:continue` in the same session, so the agent already knows the task; then the
branch (after a `/clear`), matching the task id in the branch name against the `Git:` lines; then
`flow-find-leaf` as the last resort. If context and branch disagree, both are shown and the user is
asked **before** the scenario; the same applies when `flow-find-leaf` itself returns more than one
candidate. These are the only two cases where a question about the task arises at all.

### D3. Scenario format and defaults (step 3)

One block: a header of facts, a numbered list of actions, a separate list of what is deliberately
*not* done, and the single question. Numbering is continuous so a correction can be short
("everything but 4").

```
Задача claude-tools-elf.59 — flow:done: сократить число подтверждений
Ветка  feature/claude-tools-elf.59-flow-done → влита в origin/master (squash, PR #138 MERGED)

Сделаю:
  1. закрою задачу claude-tools-elf.59
  2. удалю план docs/superpowers/plans/2026-09-01-flow-done-consolidation.md
  3. удалю worktree .worktrees/feature-claude-tools-elf.59-flow-done
  4. удалю локальную ветку (через -D: squash-мердж, -d откажет)
  5. удалю ветку на origin
  6. удалю review ledger PR #138 (PR смержен, ревью закрыто)
  7. синхронизирую beads (flow-sync push)

Не буду:
  8. закрывать эпик claude-tools-elf — все дети закрыты, но эпики пополняются

Выполнять? («да», или скажи, что изменить)
```

| Item | Default | Appears when |
|---|---|---|
| Close the task | do | always |
| Plan file | **delete**; **none** when several candidates match | a plan was found |
| Worktree | delete | we are in a worktree, branch matches the task, mergedness confirmed |
| Local branch | delete, `-D` under squash | mergedness confirmed, branch matches the task |
| Remote branch | delete | remote mode, branch exists, branch matches the task, mergedness confirmed, PR not `OPEN` |
| Ledger | purge when `MERGED`; **leave** when `CLOSED` or `OPEN` | PR known, ledger exists, branch matches the task |
| Container parent | close | no open children remain once this run's closures are counted, type ≠ `epic` |
| Epic parent | **do not close** | same condition, type `epic` |
| `flow-sync push` | do | always |

Three gates guard the deletion rows, each with its own named refusal in "Не буду":

- **the branch belongs to the task** (`flow-current-task <id>`). Otherwise mergedness is not checked
  at all — that branch's relationship to the base says nothing about this task — the header states
  that plainly, and worktree, local branch, remote branch and ledger all move to "Не буду" with the
  reason "ветка не относится к задаче". The task itself still closes and beads still sync: the work
  may have landed by another route, and refusing would make the skill unusable from `master`.
- **mergedness is confirmed** — an unconfirmed verdict (old git plus a verbal "да", or a branch with
  no commits of its own) refuses every deletion just as firmly as "not merged" would have stopped
  the run.
- **the PR is not `OPEN`**, for the remote branch alone. A branch tree can equal the base while its
  PR is still open (content landed via another PR, a cherry-pick, a rebase), and
  `git push origin --delete` then **closes that PR** — an irreversible external action the line
  "удалю ветку на origin" does not announce. The two rules about the same PR must point the same
  way: an `OPEN` PR keeps both its ledger and its branch.

**Several plan candidates get no default deletion.** The plan row then lists every candidate and
defaults to touching none — filed under "Не буду" with the list as the reason. Deleting the wrong
plan file is not recoverable from the summary; the user names the right one as a correction.

Epics are excluded from automatic closing because they are long-lived and keep gaining children.
The cost of the opposite error is on record: `claude-tools-5dl.9` was closed while `.9.2` and `.9.3`
were still open, and `bd graph` then dropped the edge to the epic and surfaced both children as
separate roots — the damage was noticed only through a visibly broken task tree.

Two rules replace the tests this text-only approach cannot have:

**D3.1. Mandatory sweep.** The nine rows above are a checklist: each must either appear as a line or
be omitted for an explicitly named reason. A skipped row now means a silent action or a silent
omission, not merely an unasked question.

**D3.2. "Не буду" lists only deliberate refusals** — the epic; the ledger of a `CLOSED` or `OPEN`
PR; the remote branch when its PR is `OPEN`; every branch-gated row when the branch does not belong
to the task; every deletion when mergedness is unconfirmed; the plan when several candidates match.
What is simply absent from the environment (no remote, no plan, not in a worktree) is not printed at
all: the scenario states decisions, not an inventory.

`-D` is no longer a second question after `-d` refuses. The merge strategy is known in advance, so
the scenario says up front which flag will be used and why.

### D4. Handling the answer (step 4)

- **Approval** ("да", "ок") → execute, no further questions.
- **Correction** ("да, но локальную ветку оставь", "всё кроме 4", "закрой и эпик") → apply, reprint
  the **whole** scenario in the same format and numbering with changed lines marked, ask again.
  Unlimited iterations.
- **Refusal** ("нет") → do nothing at all, including closing the task; report that nothing changed.
- **Unclear correction** → ask about *that item only*, then reprint the scenario and ask normally.

The scenario is reprinted in full rather than as a diff: a correction can move items between
"Сделаю" and "Не буду", and what matters at that moment is the resulting state. The second
confirmation exists to guarantee the correction was understood — a diff does not show that.

### D5. Execution and errors (steps 5–6)

Fixed order — beads first, git second:

1. `bd close <task-id>`
2. container parents, bottom-up
3. plan: `rm` (or `mv` to the archive) + `flow-link-doc <task> Plan ""`
4. `flow-sync push`
5. leave the worktree → `git worktree remove` → `git checkout <BASE_LOCAL>` (the local branch
   name — checking out `BASE_REF`/`origin/master` detaches HEAD and breaks the pull) → `git pull` →
   `git branch -d|-D` → `git push origin --delete` (only when the scenario listed it)
6. `flow-review-ledger purge`
7. summary

Beads precedes git for the same reason as today's steps 7 and 8: the git part can fail on a dirty
worktree, and by then the closed task must already be recorded and synced. The ledger goes last,
after branch deletion is confirmed: `purge` is irreversible and keeps no backup.

Execution errors do not block. Each failed item produces a line in the summary and the rest
continues. One coupling: if `git worktree remove` fails, deleting the local branch is skipped (we
are still on it) — also a summary line.

The summary lists the scenario items with their actual outcome and names divergences explicitly:

```
Выполнено:
  1. ✓ задача claude-tools-elf.59 закрыта
  2. ✓ план удалён
  3. ✗ worktree не удалён: содержит незакоммиченные изменения
  4. — локальная ветка не удалена (worktree занят)
  5. ✓ ветка на origin удалена
  6. ✓ ledger PR #138 удалён
  7. ✓ beads синхронизированы

Осталось вручную: git worktree remove --force .worktrees/feature-claude-tools-elf.59-flow-done
```

The approval was given once and in advance — to a list, not to each action as it happened — so the
summary is obliged to show where the promise was not kept.

## What this replaces in SKILL.md

Removed: step 1 as a PR gate, the separate questions 4.2, 5/6, 8.3 and the `-D` follow-up, the
`CLOSED` ledger question, and the "feature branch without PR" exit. Quick Reference, Red Flags,
Common Rationalizations and Examples are rewritten — they describe the "ask at every step" model
throughout and would otherwise contradict the body of the skill.

## Out of scope

- **GitLab (`glab`)** — `claude-tools-elf.50`. Generalising the criterion to git removes the false
  exit on GitLab repositories, but no MR-specific lines appear.
- **Tasks with several `Git:` branches** — `claude-tools-elf.51`. The scenario is built for the
  current branch, as today.
- **Configurable defaults** (e.g. always keep plans) — the `delete` default plus a one-phrase
  correction covers it.
- **A `flow-done-plan` helper** — considered and rejected, see Alternatives.

## Alternatives considered

**B. A `flow-done-plan` helper plus execution in the skill.** State collection and scenario
assembly become a pure function of the environment, testable in `plugins/flow/bin/tests` like the
other helpers, with execution left in the skill so the helper can destroy nothing. Rejected: the
scenario depends on a large combination of environment states (mode, platform, mergedness, parent
types, plan sources, worktree), and a script covering all of them is brittle where a prose
checklist is adaptable. The risk accepted in exchange is scenario drift between runs; D3.1 and D3.2
are the mitigation.

**C. Hybrid** — a helper for the facts (mergedness, task-from-branch), assembly in the skill.
Rejected with B, for the same reason and with less benefit.

## Acceptance

The skill has no automated tests and executes from the installed plugin release, not from the
working copy, so acceptance is a manual checklist run after the release:

1. remote repository, squash-merged PR, work in a worktree → full scenario, answer "да", summary
   without divergences;
2. same case, answer "да, но локальную ветку оставь" → rebuilt scenario, branch survives;
3. branch not merged → safety check and the `finishing-a-development-branch` suggestion, nothing
   changed;
4. repository without remotes → scenario without PR, remote-branch and ledger items, mergedness
   determined via `merge-tree`;
5. parent epic with all children closed → line in "Не буду", epic still open;
6. `flow:done` run from `master` (branch does not belong to the task) → header says mergedness was
   not checked, task closes and syncs, worktree/branch/ledger rows are named refusals;
7. merged branch whose PR is still `OPEN` → the remote branch stays, with the reason named, and the
   PR is still open afterwards;
8. non-epic container parent whose only remaining open child is the task being closed → the parent
   appears under "Сделаю", and after the run both the task and the parent are closed while the epic
   above them is not. This is the one automatic action the design introduces on a task other than
   the one being closed, and cases 1–5 never exercise it: their parent was an epic every time.

Cases 1–3 and 5–6 run on this repository on the next task after the release; case 4 on the user's
local-only repository; case 7 on the next branch whose content lands through another PR; case 8 on
the next task that sits under a non-epic parent.
