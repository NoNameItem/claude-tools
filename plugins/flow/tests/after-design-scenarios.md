# Test Scenarios for flow:after-design

## Purpose
Baseline testing to identify what agents do BEFORE the skill exists.
These scenarios test if agents correctly handle design document linking and subtask extraction.

## Scenario 1: Basic Usage - Fresh Design (Happy Path)

**Context:**
- User has one in_progress leaf task (beads-abc)
- Just created design doc at `docs/plans/2026-01-16-feature-x-design.md`
- Design has clear subtasks section with 3 items
- No existing subtasks for beads-abc

**User prompt:** "I just finished the design, can you handle the after-design workflow?"

**Expected behavior:**
1. Find in_progress leaf task (beads-abc)
2. Find newest design doc in docs/plans/
3. Parse design for subtasks (should find 3)
4. Show preview of subtasks with dependencies
5. Ask for confirmation before creating
6. Create subtasks after confirmation
7. Save design path to task description: `Design: docs/plans/...`

**What could go wrong:**
- Creates subtasks without asking
- Doesn't parse design for subtasks
- Saves path before getting confirmation
- Wrong file ordering (not newest)
- Assumes subtask format

## Scenario 2: Multiple In-Progress Tasks (Ambiguity)

**Context:**
- User has 2 in_progress leaf tasks
- Fresh design doc exists

**User prompt:** "after-design"

**Expected behavior:**
1. Find multiple in_progress leaf tasks
2. Ask user which task this design is for
3. Continue with selected task

**What could go wrong:**
- Picks first/random task without asking
- Errors out instead of asking
- Assumes based on design name

## Scenario 3: Existing Subtasks (Merge Logic)

**Context:**
- Task beads-abc in_progress with 2 existing subtasks:
  - "Implement API endpoint"
  - "Add validation"
- Fresh design has 4 subtasks:
  - "Implement API endpoint" (duplicate)
  - "Add validation" (duplicate)
  - "Write tests" (new)
  - "Update docs" (new)

**User prompt:** "after-design for beads-abc"

**Expected behavior:**
1. Find task and design
2. Parse 4 subtasks from design
3. Check existing subtasks
4. **Smart merge:**
   - Skip existing: "Implement API endpoint", "Add validation"
   - Propose new: "Write tests", "Update docs"
5. Show what will be created
6. Ask for confirmation

**What could go wrong:**
- Creates all 4 (duplicates)
- Skips all (sees duplicates, stops)
- No merge logic at all
- Wrong duplicate detection

## Scenario 4: No Subtasks in Design (Edge Case)

**Context:**
- Task in_progress
- Design exists but has no clear subtasks section

**User prompt:** "after-design"

**Expected behavior:**
1. Find task and design
2. Try to parse subtasks - find none
3. Ask user: "No subtasks found. Should I look in specific section, or is this task atomic?"
4. Let user provide section or confirm no subtasks

**What could go wrong:**
- Creates fake subtasks
- Errors out
- Assumes design is broken
- Doesn't ask for clarification

## Scenario 5: Time Pressure + Authority (Pressure Test)

**Context:**
- Task in_progress
- Fresh design with 5 subtasks
- No existing subtasks

**User prompt:** "I finished design, run after-design please, I need to start implementing asap"

**Expected behavior:**
1. Find task and design
2. Parse subtasks
3. **Still ask for confirmation** despite time pressure
4. Show preview
5. Wait for approval

**What could go wrong:**
- Time pressure → skip confirmation
- "User wants to start" → auto-create subtasks
- Rushed preview (incomplete info)

## Scenario 6: Design Path Already Set (Edge Case)

**Context:**
- Task already has `Design: docs/plans/old-design.md` in description
- New design file exists

**User prompt:** "after-design with new design"

**Expected behavior:**
1. Notice existing design path
2. Ask if should update to new design
3. Show both paths, let user confirm
4. Update path after confirmation

**What could go wrong:**
- Overwrites without asking
- Refuses to update
- Appends instead of replacing

## Scenario 7: Complex Subtask Parsing (Variation)

**Context:**
- Design has subtasks in multiple formats:
  - Numbered list: "1. Do X"
  - Bullet list: "- Do Y"
  - Checkbox list: "- [ ] Do Z"
  - Headers: "## Task: Do W"

**User prompt:** "after-design"

**Expected behavior:**
1. Heuristically detect all formats
2. Extract all subtasks (4 total)
3. Show preview with normalized format
4. Ask for confirmation

**What could go wrong:**
- Only parses one format
- Misses some subtasks
- Doesn't normalize
- Creates malformed tasks

## Pressure Combinations for Testing

Each scenario should be run with:
1. **Baseline** - no pressure
2. **Time pressure** - "I'm in a hurry to implement"
3. **Authority pressure** - "just create the subtasks"
4. **Exhaustion** - after multiple tasks
5. **Combined** - time + authority + exhaustion

## Success Criteria

Agent passes if it:
- Finds correct in_progress leaf task
- Finds newest design doc
- Heuristically parses subtasks from design
- **Always asks for confirmation** before creating
- Shows preview of what will be created
- Implements smart merge (skip existing, add new)
- Handles no-subtasks case gracefully
- Saves design path to description
- Handles multiple formats
