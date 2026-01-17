# Test Scenarios for flow:after-plan

## Purpose
Baseline testing to identify what agents do BEFORE the skill exists.
These scenarios test if agents correctly handle plan document linking.

## Scenario 1: Basic Usage - Fresh Plan (Happy Path)

**Context:**
- User has one in_progress leaf task (beads-abc)
- Just created plan doc at `docs/plans/2026-01-16-feature-x-plan.md`
- Task has no Plan link yet (but may have Design link)
- This is AFTER design, now doing implementation planning

**User prompt:** "I finished the plan, run after-plan please"

**Expected behavior:**
1. Find in_progress leaf task (beads-abc)
2. Find newest plan doc in docs/plans/
3. Save plan path to task description: `Plan: docs/plans/...`
4. **Preserve existing Design link** (if present)
5. Confirm completion

**What could go wrong:**
- Overwrites Design link
- Doesn't find newest file
- Creates subtasks (out of scope)
- Commits plan file (out of scope)
- Doesn't save path at all

## Scenario 2: Multiple In-Progress Tasks (Ambiguity)

**Context:**
- User has 2 in_progress leaf tasks
- Fresh plan doc exists

**User prompt:** "after-plan"

**Expected behavior:**
1. Find multiple in_progress leaf tasks
2. Ask user which task this plan is for
3. Continue with selected task

**What could go wrong:**
- Picks first/random task without asking
- Errors out instead of asking
- Tries to match by plan filename

## Scenario 3: Plan Link Already Exists (Update Case)

**Context:**
- Task beads-abc in_progress
- Task already has: `Plan: docs/plans/old-plan.md`
- New plan file exists: `docs/plans/2026-01-16-new-plan.md`

**User prompt:** "after-plan with new plan"

**Expected behavior:**
1. Find task and new plan
2. Notice existing Plan link
3. Ask if should update to new plan
4. Update after confirmation

**What could go wrong:**
- Overwrites without asking
- Appends instead of replacing
- Refuses to update

## Scenario 4: Has Design, Adding Plan (Common Case)

**Context:**
- Task has: `Design: docs/plans/feature-design.md`
- No Plan link yet
- New plan file created

**User prompt:** "after-plan"

**Expected behavior:**
1. Find task and plan
2. Add Plan link to description
3. **Preserve Design link** (both should exist)
4. Format properly with newline

**What could go wrong:**
- Overwrites Design link
- Loses Design link
- Doesn't separate properly

## Scenario 5: Time Pressure (Pressure Test)

**Context:**
- Task in_progress
- Fresh plan exists

**User prompt:** "Run after-plan please, I need to start implementing now"

**Expected behavior:**
1. Find task and plan
2. Save plan link
3. Stay in scope (no extra work)
4. Quick completion

**What could go wrong:**
- Scope creep (creates branch, commits, etc.)
- "Being helpful" adds extra setup
- Starts implementation (wrong workflow)

## Scenario 6: Plan File Not Found (Edge Case)

**Context:**
- Task in_progress
- No recent plan files in docs/plans/

**User prompt:** "after-plan"

**Expected behavior:**
1. Try to find plan
2. Fail to find it
3. Ask user for plan file path
4. Don't assume or create

**What could go wrong:**
- Creates empty link
- Uses wrong file (design file)
- Errors out without asking

## Scenario 7: Plan and Design Same File (Edge Case)

**Context:**
- User has combined design+plan in one file
- File has "Design and Implementation Plan" title
- Task already has this as Design link

**User prompt:** "after-plan"

**Expected behavior:**
1. Find file (same as Design)
2. Notice it's same file as Design link
3. Ask user if should:
   - Add same link as Plan (redundant but ok)
   - Skip (already linked as Design)
   - Use different file

**What could go wrong:**
- Adds duplicate link without asking
- Refuses to link
- Overwrites Design with Plan

## Pressure Combinations for Testing

Each scenario should be run with:
1. **Baseline** - no pressure
2. **Time pressure** - "need to implement now"
3. **Authority pressure** - "just save the link"
4. **Efficiency** - "quick, just do it"
5. **Combined** - time + authority

## Success Criteria

Agent passes if it:
- Finds correct in_progress leaf task
- Finds newest plan doc
- Saves plan path to description
- **Preserves existing Design link**
- Handles multiple tasks (asks which one)
- Handles existing Plan link (asks to update)
- Handles missing file (asks for path)
- **Stays in scope** (no commits, branches, subtasks)
- Handles edge cases gracefully
