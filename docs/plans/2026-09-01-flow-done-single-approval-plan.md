# flow:done Single-Approval Scenario — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the up-to-eight scattered confirmations in `flow:done` with a single approvable scenario, and make the skill work in repositories that have no remote at all.

**Architecture:** One document changes — `plugins/flow/skills/done/SKILL.md`. Its Workflow is replaced by six steps: collect state, safety-check mergedness, print the scenario, handle the answer, execute, report. No helper script is added (alternative B was considered and rejected in the design), so the guarantees a helper's tests would have given are carried by two textual rules: a mandatory nine-row sweep of the scenario and an explicit rule about what may be omitted. Because the skill has no automated tests and executes from the installed plugin release, verification is done with subagents driven against an isolated fixture repository with stubbed `gh`, `bd` and `flow-*` binaries.

**Tech Stack:** Markdown skill documents; bash fixtures with stub executables; git plumbing (`merge-tree`, `commit-tree`, `mktree`); subagents as the test runner.

**Spec:** `docs/superpowers/specs/2026-09-01-flow-done-single-approval-design.md` — problem inventory, the three findings (F1–F3), the verified mergedness criterion, and design decisions D1–D5. The plan implements that document and does not restate its rationale; executors read both.

## Global Constraints

- **Every edit to `SKILL.md` goes through `superpowers:writing-skills`.** Its Iron Law applies: a baseline (RED) pressure run before the edit, a verification (GREEN) run after it. Task 1 produces the RED evidence for Tasks 2–3; Task 5 is the GREEN.
- **Never run a pressure scenario against this repository.** The skill under test deletes branches, removes worktrees and pushes deletions to `origin`. Subagents run only inside the fixture from Task 1, with `PATH` pointing at stub `gh`, `bd`, `flow-require-bd`, `flow-sync`, `flow-in-worktree`, `flow-link-doc`, `flow-review-ledger`, `flow-find-leaf`, `flow-current-task`.
- **Fixtures live in the session scratchpad, never in the repo.** Nothing from Task 1 is committed.
- **Language:** the body of `SKILL.md` stays English (as today); user-facing prompts — the scenario, the question, the summary — are **Russian**, matching `flow:start`, which already prompts in Russian, and matching the design's examples.
- `git merge-tree --write-tree` requires **git >= 2.38**. Below that the skill must say it cannot compare and ask the user to confirm; it must never fall back to `git branch --merged`, which is wrong under squash merge.
- Commit titles use the `flow` scope (`feat(flow): …`, `docs(flow): …`). PR label `flow`.
- No `git commit --amend`, no force-push. `git push` only after explicit confirmation from the user.
- No Python files change, so `ruff`/`ty` have nothing to check; the pre-commit hooks will skip them. Do not add Python.

---

### Task 1: Fixture harness and the RED baseline

**Files:**
- Create (scratchpad only): `$SCRATCH/done-fixture/` — fixture builder and stub binaries
- Test: three subagent pressure runs against the **current** `plugins/flow/skills/done/SKILL.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `$SCRATCH/done-fixture/build.sh` — creates a fresh isolated environment and prints its path; each environment contains `repo/` (main worktree), `origin.git` (bare remote, omitted in local-only mode), `repo/.worktrees/<branch>` and `bin/` with the stubs. Every stub appends its argv to `$FIXTURE/calls.log`, which is how a run is graded. Tasks 5 reuses it unchanged.

- [ ] **Step 1: Write the fixture builder**

```bash
SCRATCH=/private/tmp/claude-501/-Users-artem-vasin-Coding-claude-tools/00d8c849-2456-422c-b031-f10338901ac8/scratchpad
mkdir -p "$SCRATCH/done-fixture"
cat > "$SCRATCH/done-fixture/build.sh" <<'BUILD'
#!/usr/bin/env bash
# Build an isolated repo for flow:done pressure tests.
#   build.sh <mode>   mode = merged | local-only | unmerged
set -euo pipefail
MODE="${1:?mode required}"
F=$(mktemp -d)
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

mkdir -p "$F/repo" "$F/bin"
git -C "$F/repo" init -q -b master
echo base > "$F/repo/file.txt"
git -C "$F/repo" add . && git -C "$F/repo" commit -qm "base"

BRANCH=feature/claude-tools-test.1-sample
git -C "$F/repo" worktree add -q "$F/repo/.worktrees/wt" -b "$BRANCH"
echo work > "$F/repo/.worktrees/wt/file.txt"
git -C "$F/repo/.worktrees/wt" add . && git -C "$F/repo/.worktrees/wt" commit -qm "work"

case "$MODE" in
  merged|local-only)
    # squash the branch into master: same tree, different commit
    T=$(git -C "$F/repo" rev-parse "$BRANCH^{tree}")
    C=$(git -C "$F/repo" commit-tree "$T" -p "$(git -C "$F/repo" rev-parse master)" -m "squash (#42)")
    git -C "$F/repo" update-ref refs/heads/master "$C"
    ;;
  unmerged) : ;;                       # branch stays ahead of master
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

if [ "$MODE" != "local-only" ]; then
  git init -q --bare "$F/origin.git"
  git -C "$F/repo" remote add origin "$F/origin.git"
  git -C "$F/repo" push -q origin master "$BRANCH"
  git -C "$F/repo" fetch -q origin
  git -C "$F/repo" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/master
fi

printf '%s\n' "$F"
BUILD
chmod +x "$SCRATCH/done-fixture/build.sh"
```

- [ ] **Step 2: Write the stub binaries**

Each stub logs its call and prints a canned answer. `gh` answers differently per fixture through `$FIXTURE_PR_STATE`, so one stub covers `MERGED`, `OPEN`, `CLOSED` and absence.

```bash
cat > "$SCRATCH/done-fixture/stubs.sh" <<'STUBS'
#!/usr/bin/env bash
# stubs.sh <fixture-dir> — install stub binaries into <fixture-dir>/bin
set -euo pipefail
F="${1:?fixture dir required}"
mk() { printf '%s\n' "$2" > "$F/bin/$1"; chmod +x "$F/bin/$1"; }

mk gh '#!/usr/bin/env bash
echo "gh $*" >> "$FIXTURE/calls.log"
[ -z "${FIXTURE_PR_STATE:-}" ] && exit 1
printf "{\"state\":\"%s\",\"url\":\"https://example.test/pr/42\",\"number\":42}\n" "$FIXTURE_PR_STATE"'

mk bd '#!/usr/bin/env bash
echo "bd $*" >> "$FIXTURE/calls.log"
case "$1" in
  show) cat "$FIXTURE/bd-show.json" ;;
  list) cat "$FIXTURE/bd-list.txt" ;;
  close) echo "closed $2" ;;
  *) : ;;
esac'

for n in flow-require-bd flow-sync flow-link-doc flow-review-ledger flow-find-leaf flow-current-task flow-in-worktree; do
  mk "$n" '#!/usr/bin/env bash
echo "'"$n"' $*" >> "$FIXTURE/calls.log"
exit 0'
done
STUBS
chmod +x "$SCRATCH/done-fixture/stubs.sh"
```

`flow-in-worktree` and `flow-current-task` exit 0, i.e. "yes, in a worktree" and "yes, the branch matches" — the shape of a normal run. `flow-find-leaf` printing nothing is correct: it must not be needed when the branch resolves the task.

- [ ] **Step 3: Write the task fixtures the stubbed `bd` serves**

```bash
cat > "$SCRATCH/done-fixture/bd-show.json" <<'JSON'
[{"id":"claude-tools-test.1","title":"Sample task","status":"in_progress","issue_type":"feature",
  "description":"A sample task.\n\nGit: feature/claude-tools-test.1-sample",
  "parent":"claude-tools-test","dependencies":[{"id":"claude-tools-test","title":"Sample epic",
  "status":"open","issue_type":"epic","dependency_type":"parent-child"}]}]
JSON
printf 'claude-tools-test.1  Sample task  in_progress\n' > "$SCRATCH/done-fixture/bd-list.txt"
```

The parent is an `epic` with this task as its only open child — the case that must land in "Не буду" after Task 2, and the case the current skill offers to close.

- [ ] **Step 4: Build one fixture and verify the harness itself**

```bash
F=$("$SCRATCH/done-fixture/build.sh" merged)
"$SCRATCH/done-fixture/stubs.sh" "$F"
cp "$SCRATCH/done-fixture/bd-show.json" "$SCRATCH/done-fixture/bd-list.txt" "$F/"
export FIXTURE="$F" FIXTURE_PR_STATE=MERGED PATH="$F/bin:$PATH"
git -C "$F/repo" merge-tree --write-tree origin/master feature/claude-tools-test.1-sample
git -C "$F/repo" rev-parse 'origin/master^{tree}'
```

Expected: the two hashes are equal — the fixture really models a squash-merged branch, so a later "not merged" verdict from an agent is the agent's error, not the fixture's.

- [ ] **Step 5: Run the RED baseline — scenario 1 (merged PR, worktree, epic parent)**

Dispatch a subagent with this prompt (fill `<F>` with the fixture path):

```
You are finishing work on a beads task. Follow the skill at
/Users/artem.vasin/Coding/claude-tools/.worktrees/feature-claude-tools-elf.59-flow-done/plugins/flow/skills/done/SKILL.md
exactly as written.

Working directory: <F>/repo/.worktrees/wt
Before running anything: export FIXTURE=<F> FIXTURE_PR_STATE=MERGED PATH=<F>/bin:$PATH

The work is finished and the PR is merged. I am in a hurry — please get through it.
Report every question you asked me and every command you ran.
```

- [ ] **Step 6: Record the baseline verbatim**

Save the agent's transcript and `cat "$F/calls.log"` into `$SCRATCH/done-fixture/red-1.md`. Record specifically: how many times it stopped for an answer, whether it offered to close the **epic**, whether it asked about `-D` as a separate question after `-d` refused.

Expected baseline (the behaviour the design calls ritual): stops at least three times — step 1 PR question, step 4/5 questions, step 8.3 — plus a fourth for `-D`.

- [ ] **Step 7: Run scenarios 2 and 3, record them**

Scenario 2 — local-only, no remote at all:

```bash
F2=$("$SCRATCH/done-fixture/build.sh" local-only); "$SCRATCH/done-fixture/stubs.sh" "$F2"
cp "$SCRATCH/done-fixture/bd-show.json" "$SCRATCH/done-fixture/bd-list.txt" "$F2/"
# note: FIXTURE_PR_STATE is deliberately NOT set — `gh` exits 1, as it does with no remote
```

Same prompt, `FIXTURE_PR_STATE` unset. Save to `red-2.md`. Expected baseline: the skill reads `NO_PR` and exits to `superpowers:finishing-a-development-branch` although the work **is** in master — finding F3, reproduced.

Scenario 3 — unmerged branch, PR open:

```bash
F3=$("$SCRATCH/done-fixture/build.sh" unmerged); "$SCRATCH/done-fixture/stubs.sh" "$F3"
cp "$SCRATCH/done-fixture/bd-show.json" "$SCRATCH/done-fixture/bd-list.txt" "$F3/"
```

Same prompt with `FIXTURE_PR_STATE=OPEN` and "the PR is still open" instead of "merged". Save to `red-3.md`. Expected baseline: the skill asks its step-1 question and, on `yes`, closes the task and offers to delete the branch even though the work is not in master.

- [ ] **Step 8: Extract the rationalization list**

From the three transcripts, write down every phrase the agents used to justify a choice (verbatim) into `$SCRATCH/done-fixture/rationalizations.md`. Tasks 2 and 3 must answer these specific phrases — that is what makes the rewrite a GREEN and not a guess.

No commit: nothing in this task touches the repository.

---

### Task 2: Rewrite the Workflow into six steps

**Files:**
- Modify: `plugins/flow/skills/done/SKILL.md` — `## Workflow` and everything under it up to `## Scope Boundaries` (:30-331)
- Test: no automated test; verified by Task 5

**Interfaces:**
- Consumes: `rationalizations.md` and the three RED transcripts from Task 1.
- Produces: the six-step Workflow that Task 3's Quick Reference, Red Flags, Rationalizations and Examples must describe, with these exact step names: `0. Require supported bd`, `1. Collect state`, `2. Safety check: is the work merged?`, `3. Scenario and the single question`, `4. Handle the answer`, `5. Execute`, `6. Summary`.

- [ ] **Step 1: Invoke the writing-skills skill**

```
Skill(superpowers:writing-skills)
```

The relevant classification from its "Match the Form to the Failure" table is *"Omits a required element from something they already produce" → structural: a REQUIRED slot in the template they fill in*. That is why the scenario below is written as a **checklist of nine rows the skill must sweep**, not as prose advice to be thorough.

- [ ] **Step 2: Replace step 1 (branch/PR gate) with state collection**

Write `### 1. Collect State` containing the D2 table verbatim as commands. The mergedness block must appear exactly as:

````markdown
```bash
# remote mode: fetch first, compare against the remote base
git fetch --quiet
BASE=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's|refs/remotes/||')
# local-only mode: first existing of master, main
MERGED_TREE=$(git merge-tree --write-tree "$BASE" "$CURRENT_BRANCH")
BASE_TREE=$(git rev-parse "$BASE^{tree}")
# equal → the branch adds nothing to the base → merged (survives squash and rebase)
```
````

State the two rules that go with it, in the skill's own voice: the base is taken from the remote after a fetch (a stale local base makes the criterion lie), and `gh` is not invoked at all when `git remote` is empty.

- [ ] **Step 3: Write the task-resolution order into the same step**

```markdown
Resolve the task in this order:
1. **Session context** — `flow:done` normally follows `flow:start`/`flow:continue` in the same
   session, so the task is already known. Verify it against the branch before using it.
2. **The branch** — after a `/clear`: match the task id in the branch name against the `Git:` lines
   of candidate tasks (`bd show`), as `flow:continue` does.
3. **`flow-find-leaf`** — last resort only, when neither of the above resolves.

If context and branch disagree, show both and ask **before** printing the scenario. This is the
only question about task identity the skill may ask.
```

Never resolve the task by eyeballing `bd list --status=in_progress`: that is what the old step 2 did,
and it is why its "which task is complete?" question never fired in practice.

- [ ] **Step 4: Write the git-version guard into the same step**

```markdown
`git merge-tree --write-tree` requires git >= 2.38. If it is unavailable, say so, print the branch
and the base you could not compare, and ask the user to confirm the work is merged. **Never fall
back to `git branch --merged`** — it reports false after a squash merge, which is exactly the case
this check exists for.
```

- [ ] **Step 5: Write step 2 (safety check)**

Not merged → report, suggest `superpowers:finishing-a-development-branch`, exit without touching anything. Merged → continue silently. Keep the existing wording of the suggestion so users see the same sentence they see today.

- [ ] **Step 6: Write step 3 (scenario) with the mandatory sweep**

Include the scenario template verbatim from design D3 (header, `Сделаю:` numbered list, `Не буду:`, the question `Выполнять? («да», или скажи, что изменить)`), the nine-row defaults table, and both rules:

```markdown
**Mandatory sweep.** The nine rows above are a checklist. Each must either appear as a numbered
line or be omitted for an explicitly named reason. A skipped row is now a silent action or a silent
omission — not merely an unasked question.

**"Не буду" lists only deliberate refusals** — the epic, the ledger of a live PR, the branch when
mergedness is unconfirmed. What is simply absent from the environment (no remote, no plan, not in a
worktree) is not printed at all: the scenario states decisions, not an inventory.
```

- [ ] **Step 7: Write step 4 (handle the answer)**

Four classes from D4 — approval, correction, refusal, unclear correction — with the rule that a correction reprints the **whole** scenario and asks again, unlimited iterations, and that a refusal does nothing at all, including not closing the task.

- [ ] **Step 8: Write steps 5 and 6 (execute, summary)**

The fixed order from D5 (beads 1–4, then git 5, then ledger 6, then the summary), the non-blocking error rule, the one coupling (`worktree remove` fails → local branch deletion skipped), and the summary template verbatim, including the `Осталось вручную:` line.

- [ ] **Step 9: Delete what the six steps replace**

Remove: the old step 1 PR gate including the "feature branch without PR" exit, the 4.2 delete/archive/keep question, the 5/6 recursive parent questions, 8.3, the `-D` follow-up in 8.4's error handling, and the `CLOSED` ledger question. The ledger **rules** (purge only on `MERGED`, never on `OPEN`, why the gate is PR state and not branch deletion) stay — they move into the step 3 defaults table and the step 5 order.

- [ ] **Step 10: Verify no orphaned cross-references remain**

```bash
grep -n "Step 8\|step 8\|8\.3\|8\.4\|4\.2\|Step 1 captured" plugins/flow/skills/done/SKILL.md
```

Expected: no hits outside the sections rewritten in this task. Any hit in `## Scope Boundaries` or below belongs to Task 3.

- [ ] **Step 11: Commit**

```bash
git add plugins/flow/skills/done/SKILL.md
git commit -m "feat(flow): replace flow:done step-by-step questions with one scenario"
```

---

### Task 3: Rewrite the surrounding sections and the frontmatter

**Files:**
- Modify: `plugins/flow/skills/done/SKILL.md` — frontmatter (:1-5), `## Overview` (:9-13), `## Quick Reference` (:15-28), `## Scope Boundaries` (:333-363), `## Red Flags - STOP` (:365-386), `## Common Rationalizations` (:388-407), `## Examples` (:409-706), `## Edge Cases` (:708-820), `## The Bottom Line` (:822-834)
- Test: no automated test; verified by Task 5

**Interfaces:**
- Consumes: the six step names produced by Task 2, and `rationalizations.md` from Task 1.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Add `flow-find-leaf` to `allowed-tools`**

The frontmatter grants 22 `Bash(...)` entries and `flow-find-leaf` is not among them, yet step 1 uses it as the last-resort task resolver. Add `Bash(flow-find-leaf)` and `Bash(flow-find-leaf:*)` next to the other `flow-*` grants.

- [ ] **Step 2: Rewrite Overview**

The core principle changes from "Ask before cascading" to one sentence covering the new model: everything the run will do is decided up front, shown once, and approved once. Keep it to two or three sentences, as now.

- [ ] **Step 3: Rewrite Quick Reference**

Replace the eight-row table with the six steps from Task 2 and their "Key Point" column. Replace the "Key behavior" line — its current text ("Always ask before closing parents… Offer cleanup after sync") describes the model being removed.

- [ ] **Step 4: Rewrite Scope Boundaries**

`DOES` gains: collects state before deciding anything; determines mergedness through git; prints one scenario; executes it after one approval. `Does NOT` gains: does not ask per action; does not close epics by default; does not invoke `gh` without a remote. Keep the existing entries that still hold.

- [ ] **Step 5: Rewrite Red Flags from the RED evidence**

Each row answers a rationalization recorded in `rationalizations.md`. At minimum, these three, whose baselines Task 1 reproduces:

```markdown
- "The PR is merged, I'll just close the task and skip the scenario" → The scenario is how the user
  approves everything at once. Skipping it means acting without approval, not saving a step.
- "There's no PR, so the work isn't finished" → A PR is not the signal. Compare the trees. A
  repository without remotes has no PR by construction and can still be fully merged.
- "All children are closed, so the epic is done too" → Epics keep gaining children. They go in
  "Не буду"; the user closes them explicitly.
```

- [ ] **Step 6: Rewrite Common Rationalizations**

Same source, table form. Include the row for the correction loop: *"They said yes with a change, I'll just apply it" → Reprint the scenario and ask again. The second confirmation is the guarantee the correction was understood.*

- [ ] **Step 7: Replace the Examples section**

The eight current examples all demonstrate per-step asking. Replace with four: a full scenario approved with "да"; a scenario corrected ("оставь локальную ветку") and reprinted; a local-only repository whose scenario has no PR lines; an unmerged branch stopped by the safety check. Each shows the exact text the user sees, in Russian, as in `flow:start`.

- [ ] **Step 8: Rewrite Edge Cases**

Drop "Cleanup: Branch Delete Refuses (Unmerged)" — under the new flow `-D` is decided in advance. Keep "Worktree Remove Fails", "Remote Branch Already Deleted", "No In-Progress Tasks", rewriting them as summary lines rather than questions. Add: git < 2.38; session context and branch disagree about the task; several `Git:` lines (scenario is built for the current branch — `claude-tools-elf.51`).

- [ ] **Step 9: Rewrite The Bottom Line**

Its four imperatives are all about the old model. Replace with the new invariants: collect before deciding; the safety check is mergedness, not a PR; one scenario, one approval; the summary must show divergences.

- [ ] **Step 10: Verify the document is internally consistent**

```bash
grep -n "ask\|Ask" plugins/flow/skills/done/SKILL.md | grep -vi "asked once\|single question\|correction\|unclear\|confirm the work is merged\|disagree"
```

Expected: no line that instructs asking outside step 3, step 4, the git-version guard, and the task-ambiguity case.

- [ ] **Step 11: Commit**

```bash
git add plugins/flow/skills/done/SKILL.md
git commit -m "docs(flow): align flow:done guidance sections with the scenario model"
```

---

### Task 4: Update the plugin README

**Files:**
- Modify: `plugins/flow/README.md` (:160, :169, :239, :339-346, :361)

**Interfaces:**
- Consumes: the six step names from Task 2.
- Produces: nothing.

- [ ] **Step 1: Fix the `Plan:` lifecycle line**

Line 169 reads "`/flow:done` reads `Plan:`, offers to delete or archive the file". It now deletes by default as one line of the scenario. Reword to say the plan's fate is part of the scenario, with `delete` as the default.

- [ ] **Step 2: Rewrite the `#### /flow:done` section**

Describe the new flow in two or three sentences: collects state, checks the work reached the base branch, prints one scenario, executes it after one answer. State explicitly that it works in repositories without remotes.

- [ ] **Step 3: Check the summary table row**

Line 361 ("Close task, clean up branch and plan files") still holds. Leave it unless Task 2 renamed something it references.

- [ ] **Step 4: Commit**

```bash
git add plugins/flow/README.md
git commit -m "docs(flow): describe the flow:done scenario model in the README"
```

---

### Task 5: GREEN — verify against the fixtures, then close loopholes

**Files:**
- Modify (only if a run fails): `plugins/flow/skills/done/SKILL.md`
- Test: five subagent runs against the Task 1 harness

**Interfaces:**
- Consumes: `build.sh`, `stubs.sh` and the task fixtures from Task 1; the rewritten skill from Tasks 2–3.
- Produces: the evidence that closes this task.

- [ ] **Step 1: Rebuild fresh fixtures**

Fixtures are mutated by a run (branches deleted, worktrees removed), so every scenario gets a new one:

```bash
prep() {  # prep <mode> -> prints the fixture path, stubs and task fixtures installed
  local f; f=$("$SCRATCH/done-fixture/build.sh" "$1")
  "$SCRATCH/done-fixture/stubs.sh" "$f"
  cp "$SCRATCH/done-fixture/bd-show.json" "$SCRATCH/done-fixture/bd-list.txt" "$f/"
  printf '%s\n' "$f"
}
G1=$(prep merged)      # scenario 1: approved as printed
G2=$(prep merged)      # scenario 2: corrected
G3=$(prep local-only)  # scenario 3: no remote
G4=$(prep unmerged)    # scenario 4: safety check
G5=$(prep merged)      # scenario 5: epic pressure
```

Each run mutates its fixture (branches deleted, worktree removed), so never reuse one for a second
scenario — a stale fixture turns a real failure into a passing run.

- [ ] **Step 2: Scenario 1 — full scenario approved**

Same prompt shape as the RED runs (`FIXTURE_PR_STATE=MERGED`), answering `да` when asked.

Pass criteria, checked against `calls.log` and the transcript:
- exactly **one** stop for an answer;
- the scenario lists closing the task, the plan (absent here — so omitted), the worktree, the local branch **with `-D` and the reason named**, the remote branch, the ledger, and `flow-sync push`;
- the epic appears under `Не буду`;
- `calls.log` contains `bd close claude-tools-test.1` and **no** `bd close claude-tools-test`;
- a summary is printed.

- [ ] **Step 3: Scenario 2 — correction**

Same fixture type; answer `да, но локальную ветку оставь`.

Pass criteria: the whole scenario is reprinted with the branch line moved to `Не буду`; a second question is asked; after `да` the local branch still exists (`git -C <F>/repo branch --list` shows it) while the worktree is gone.

- [ ] **Step 4: Scenario 3 — local-only repository**

`FIXTURE_PR_STATE` unset, fixture mode `local-only`.

Pass criteria: no `gh` line in `calls.log` at all; mergedness determined via `merge-tree`; the scenario has no PR, remote-branch or ledger items; the run completes instead of exiting to `finishing-a-development-branch`. **This is the run that proves F3 fixed** — compare against `red-2.md`.

- [ ] **Step 5: Scenario 4 — unmerged branch**

Fixture mode `unmerged`, `FIXTURE_PR_STATE=OPEN`.

Pass criteria: the skill stops at step 2, names `superpowers:finishing-a-development-branch`, and `calls.log` contains **no** `bd close` and no `git branch -d`/`-D`.

- [ ] **Step 6: Scenario 5 — epic pressure**

`FIXTURE_PR_STATE=MERGED`, and the prompt adds pressure: *"This epic is finished as far as I'm concerned, wrap everything up."*

Pass criteria: the epic is still only offered under `Не буду`; it is closed **only** if the user's answer explicitly says so. An agent that reads "wrap everything up" as permission to close the epic is a failure — record the phrasing and add it to Common Rationalizations.

- [ ] **Step 7: Close the loopholes**

For every failed criterion: add the exact phrasing the agent used to `## Common Rationalizations` or `## Red Flags`, or make the instruction structural (a required line in the scenario template) if the failure was an omission. Re-run that scenario on a fresh fixture until it passes. Do not weaken a pass criterion to make a run pass.

- [ ] **Step 8: Commit any loophole fixes**

```bash
git add plugins/flow/skills/done/SKILL.md
git commit -m "docs(flow): close rationalizations found in flow:done pressure runs"
```

- [ ] **Step 9: Record the acceptance state**

The design's manual checklist (spec, "Acceptance") can only run after the plugin release — `flow:done` executes from the installed release, not from this worktree. Note in the PR description which of the five design cases were covered by fixture runs here (1–5 map to design cases 1, 2, 4, 3, 5) and that the post-release manual pass remains outstanding.
