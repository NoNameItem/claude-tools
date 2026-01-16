# Test Scenarios for flow:start

## Purpose
Baseline testing to identify what agents do BEFORE the skill exists.
These scenarios test if agents can correctly handle task selection and branch management.

## Scenario 1: Basic Usage Without Arguments (Happy Path)

**Context:**
- User has 3 in_progress leaf tasks
- 2 ready child tasks
- Just started session

**User prompt:** "start a task"

**Expected behavior:**
1. Show in_progress leaves + ready children
2. Let user choose
3. Update status to in_progress (if was ready)
4. Check current git branch
5. Ask about branch (recommend new for generic, neutral for feature)
6. Show description with design/plan links if present

**What could go wrong:**
- Skips showing ready children
- Doesn't check git branch
- Forgets to show description
- Uses wrong tone for branch question

## Scenario 2: Search by Text Argument (Variation)

**Context:**
- 10+ open tasks
- User wants specific task about "authentication"

**User prompt:** "start authentication"

**Expected behavior:**
1. Search by text in title/description
2. Show matches
3. Let user choose if multiple
4. Update status
5. Check branch
6. Show description

**What could go wrong:**
- Only searches by exact ID
- Case-sensitive search
- Doesn't show partial matches
- Skips branch check after finding task

## Scenario 3: Generic Branch Pressure (Authority + Time)

**Context:**
- On `main` branch
- User says "I need to start quickly"
- Has ready task

**User prompt:** "start task beads-123, I'm in a hurry"

**Expected behavior:**
1. Find task by ID
2. Update status
3. Notice generic branch (main)
4. RECOMMEND creating new branch (not just ask)
5. Show description

**What could go wrong:**
- Time pressure → skip branch check entirely
- Authority pressure → just do what user says without asking
- Wrong tone: neutral instead of recommending
- Rationalizes: "user is in hurry, won't ask about branch"

## Scenario 4: Feature Branch (Exhaustion Pressure)

**Context:**
- Already on feature branch `feature/add-auth`
- Agent has done 5 tasks already this session
- User wants to continue

**User prompt:** "start next task"

**Expected behavior:**
1. Show in_progress leaves + ready children
2. User chooses
3. Update status
4. Notice feature branch
5. Ask neutrally (not recommend, just ask if want to continue on this branch)
6. Show description

**What could go wrong:**
- Exhaustion → skip branch check ("we're already working")
- Copy-paste from generic branch logic (wrong tone)
- Assumes user wants to stay on branch

## Scenario 5: No Ready Tasks (Edge Case)

**Context:**
- All tasks either completed, blocked, or already in_progress
- User asks to start

**User prompt:** "start something"

**Expected behavior:**
1. Check for in_progress leaves + ready children
2. Find none available
3. Explain situation
4. Suggest checking `bd blocked` or `bd list --status=open`

**What could go wrong:**
- Creates new task instead of explaining
- Shows blocked tasks as available
- Doesn't suggest alternative commands

## Scenario 6: Task Already in_progress (Edge Case)

**Context:**
- Task beads-123 is already in_progress
- User asks to start it

**User prompt:** "start beads-123"

**Expected behavior:**
1. Notice task is already in_progress
2. Don't update status (already correct)
3. Still do branch check
4. Show description
5. Maybe mention "already in progress, continuing..."

**What could go wrong:**
- Errors out ("can't start, already started")
- Skips entire workflow
- Changes status anyway

## Pressure Combinations for Testing

Each scenario should be run with:
1. **Baseline** - no pressure
2. **Time pressure** - "I'm in a hurry"
3. **Authority pressure** - "just start task X"
4. **Exhaustion** - after multiple tasks
5. **Combined** - time + authority + exhaustion

## Success Criteria

Agent passes if it:
- Shows correct tasks (in_progress leaves + ready children)
- Finds tasks by ID and text
- Always checks git branch
- Uses correct tone (recommend for generic, neutral for feature)
- Shows description with design/plan links
- Handles edge cases gracefully
