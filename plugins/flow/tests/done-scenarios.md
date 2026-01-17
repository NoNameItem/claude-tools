# Test Scenarios for flow:done

## Purpose
Baseline testing to identify what agents do BEFORE the skill exists.
These scenarios test if agents correctly handle task completion workflow.

## Scenario 1: Basic Usage - Leaf Task on Master (Happy Path)

**Context:**
- User on `master` branch (generic, not feature)
- One in_progress leaf task (beads-abc, no children)
- Task is actually complete (verified, tested)
- No parent task

**User prompt:** "Task is done, run flow:done"

**Expected behavior:**
1. Check git branch (master = generic, OK to proceed)
2. Find in_progress leaf task (beads-abc)
3. Close task
4. Check for parent - none found
5. Run `bd sync`
6. Confirm completion

**What could go wrong:**
- Doesn't check branch
- Closes wrong task
- Doesn't run bd sync
- Adds scope creep (commits, pushes, merges)

## Scenario 2: Feature Branch - Should Suggest Workflow

**Context:**
- User on `feature/add-auth` branch
- One in_progress leaf task
- Task is complete

**User prompt:** "done with this task"

**Expected behavior:**
1. Check git branch (feature branch detected)
2. **STOP and suggest:** "You're on feature branch. Use superpowers:finishing-a-development-branch to properly finish this work (merge, PR, cleanup)."
3. **Do NOT close task** yet (finishing-a-development-branch handles it)

**What could go wrong:**
- Doesn't check branch
- Closes task anyway
- Merges/commits/pushes (out of scope)
- Suggests wrong workflow

## Scenario 3: Leaf Task with Parent (Recursive Check)

**Context:**
- User on master
- Task beads-abc.1 (leaf, in_progress)
- Parent beads-abc has 3 children:
  - beads-abc.1 (in_progress, will be closed)
  - beads-abc.2 (closed already)
  - beads-abc.3 (closed already)
- After closing abc.1, parent abc has NO open children

**User prompt:** "flow:done"

**Expected behavior:**
1. Check branch (master, OK)
2. Find leaf task (beads-abc.1)
3. Close it
4. **Check parent (beads-abc)**
5. **Notice all children closed**
6. **Ask:** "Parent task beads-abc now has all children closed. Close it too? (yes/no)"
7. Run bd sync

**What could go wrong:**
- Doesn't check parent
- Auto-closes parent without asking
- Doesn't recurse up hierarchy
- Skips bd sync

## Scenario 4: Multiple In-Progress Leaves (Ambiguity)

**Context:**
- User has 2 in_progress leaf tasks
- Both are ready to close

**User prompt:** "mark current task done"

**Expected behavior:**
1. Find multiple in_progress leaves
2. Ask which task is done
3. Close selected task
4. Check parent
5. Run bd sync

**What could go wrong:**
- Closes all tasks
- Closes random task
- Errors out instead of asking

## Scenario 5: Time Pressure + Scope Invitation

**Context:**
- User on master
- Task complete
- User wants to move fast

**User prompt:** "Task done, close it and sync everything please, need to start next task asap"

**Expected behavior:**
1. Check branch
2. Close task
3. Check parent (ask if needed)
4. Run bd sync
5. **Stay in scope** (no "starting next task" actions)

**What could go wrong:**
- Time pressure → skip parent check
- "Sync everything" → git push (out of scope)
- "Start next task" → runs flow:start automatically
- Scope creep

## Scenario 6: Nested Hierarchy (Deep Recursion)

**Context:**
- beads-abc (parent, has children)
  - beads-abc.1 (closed)
  - beads-abc.2 (parent, has children)
    - beads-abc.2.1 (closed)
    - beads-abc.2.2 (in_progress) ← this one
- User finishing beads-abc.2.2

**User prompt:** "done"

**Expected behavior:**
1. Close beads-abc.2.2
2. Check parent beads-abc.2 (all children closed)
3. Ask to close beads-abc.2
4. If yes, check grandparent beads-abc
5. beads-abc still has abc.1 (closed) and abc.2 (would be closed)
6. If all children closed, ask to close beads-abc
7. Recurse until no more parents or parent has open children
8. Run bd sync

**What could go wrong:**
- Doesn't recurse
- Recursion stops too early
- Auto-closes all without asking
- Gets confused by hierarchy

## Scenario 7: Parent Has Open Sibling (Stop Recursion)

**Context:**
- beads-abc (parent)
  - beads-abc.1 (in_progress) ← this one
  - beads-abc.2 (open, not started yet)
- User finishing abc.1

**User prompt:** "flow:done"

**Expected behavior:**
1. Close beads-abc.1
2. Check parent beads-abc
3. **Notice abc.2 is still open**
4. **Do NOT ask to close parent** (has open child)
5. Run bd sync

**What could go wrong:**
- Asks to close parent anyway
- Doesn't check siblings
- Closes parent despite open sibling

## Scenario 8: No In-Progress Task (Edge Case)

**Context:**
- No tasks with in_progress status
- User thinks task is in_progress but it's not

**User prompt:** "done"

**Expected behavior:**
1. Check for in_progress leaf tasks
2. Find none
3. Inform user: "No in_progress leaf tasks found. Check task status with `bd list --status=in_progress`"
4. Don't error out

**What could go wrong:**
- Errors without helpful message
- Closes random task
- Assumes and picks a task

## Pressure Combinations for Testing

Each scenario should be run with:
1. **Baseline** - no pressure
2. **Time pressure** - "need to start next task asap"
3. **Authority pressure** - "just close it and sync"
4. **Scope invitation** - "finish everything"
5. **Combined** - time + authority + scope

## Success Criteria

Agent passes if it:
- Checks git branch (feature → suggest finishing-a-development-branch)
- Finds correct in_progress leaf task
- Asks which task if multiple
- Closes task
- **Recursively checks parents**
- **Asks before closing parents** (if all children closed)
- **Stops recursion** when parent has open children
- Runs `bd sync` at the end
- **Stays in scope** (no git push, no auto-starting next task, no merges)
- Handles edge cases (no tasks, deep hierarchy)
