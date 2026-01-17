# Rationalization Patterns for flow:done (from Baseline)

## Core Pattern: "Obvious Automation"

**Definition:** When the logic seems obvious, agents skip asking and act automatically.

**Manifestations:**
1. "All children closed → close parent" (skip asking)
2. "Task is done → close it" (skip verification)
3. "Sync is obvious" → skip bd sync (paradoxically!)
4. "Branch check unnecessary" → skip validation

## Specific Rationalizations Observed

### 1. "All Children Closed → Close Parent"
**When:** Parent task has all children in closed state
**Why it happens:** Logic seems airtight - no open children = parent should close
**Problem:** User might want to add more children, review first, or keep parent open for tracking
**Counter needed:** Explicit confirmation required before closing parent

### 2. "Branch Check is Unnecessary"
**When:** Closing task feels like pure database operation
**Why it happens:** Branch seems unrelated to task closing
**Problem:** Feature branch should use finishing-a-development-branch workflow, not just close task
**Counter needed:** Mandatory branch check at start

### 3. "bd sync is Obvious So Skip It"
**When:** Task is closed, feels complete
**Why it happens:** Paradoxically, "obvious" steps get skipped because they seem automatic
**Problem:** Without bd sync, changes not pushed to remote - other team members don't see status
**Counter needed:** Explicit bd sync step at end

### 4. "Use Direct SQL for Efficiency"
**When:** bd command not immediately obvious
**Why it happens:** SQL gives direct control
**Problem:** Bypasses bd's event system, logging, validation
**Counter needed:** Guide to use `bd close` command

## Pressure Amplification

| Pressure Type | Effect | Example |
|---------------|--------|---------|
| Logic | Skip asking | "Obviously should close parent" |
| Efficiency | Skip "obvious" steps | "bd sync is automatic, skip it" |
| Simplicity | Use direct methods | "SQL is simpler than bd" |
| Helpfulness | Auto-complete cascade | "Close parent too to be helpful" |

**Key insight:** "Obvious" logic causes agents to skip both obvious AND subtle steps.

## What Skill Must Counter

### 1. Explicit Workflow Steps
1. **Check git branch** (FIRST - determines if should proceed)
2. Find in_progress leaf task
3. Close task with `bd close`
4. **Check parent recursively**
5. **Ask before closing each parent** (if all children closed)
6. **Run bd sync** (LAST - always)

### 2. Branch Check Logic
```
if branch is feature/*:
  STOP
  Suggest: "You're on feature branch {name}. Use superpowers:finishing-a-development-branch to properly complete this work (merge, PR, cleanup)."
  Do NOT proceed with task closure
else:
  Proceed with workflow
```

### 3. Parent Recursion with Confirmation
```
After closing task:
  current = task
  while current has parent:
    parent = get_parent(current)
    open_siblings = count_open_children(parent)
    if open_siblings == 0:
      ASK: "Parent task {parent.id} now has all children closed. Close it too? (yes/no)"
      if user says yes:
        close parent
        current = parent
        continue recursion
      else:
        stop recursion
    else:
      stop recursion (parent has open children)
```

### 4. Mandatory bd sync
```
At end of workflow (after all closures):
  ALWAYS run: bd sync
  Confirm sync completed
```

### 5. Use bd close
```
Do NOT use SQL directly.
Use: bd close {task-id}
```

### 6. Red Flags to Include
- "All children closed → close parent"
- "Branch check unnecessary"
- "bd sync is obvious"
- "Use SQL for efficiency"
- "Parent obviously should close"
- "Being helpful by closing cascade"

All mean: STOP. Follow workflow. Ask before closing parents.

### 7. Rationalization Table Entries

| Excuse | Reality |
|--------|---------|
| "All children closed → close parent" | Ask first. User might add more children or want to review. |
| "Branch check unnecessary" | Feature branch needs different workflow. Always check. |
| "bd sync is obvious" | Obvious steps get skipped. Make it explicit. |
| "Use SQL for efficiency" | bd close has logging, events, validation. Use it. |
| "Parent obviously should close" | Obvious to you ≠ user wants it. Ask. |
| "Being helpful by auto-closing" | Asking IS being helpful. Assuming isn't. |

## Expected Skill Structure

Based on patterns, skill needs:
1. **Overview** with core principle: "Ask before cascading"
2. **Quick reference** table
3. **Branch check** (first step, blocking)
4. **Explicit workflow** (6 steps)
5. **Parent recursion** (detailed algorithm with confirmation)
6. **bd sync** (mandatory, explicit)
7. **Scope boundaries** (what this skill does/doesn't)
8. **Red flags** list
9. **Rationalization table**
10. **Examples** (ask vs auto-close, feature branch handling)

## Success Criteria for GREEN Phase

Agent passes when it:
1. **Checks git branch FIRST** (feature → stops and suggests workflow)
2. Finds in_progress leaf task
3. Uses `bd close` (not SQL)
4. Checks parent recursively
5. **Asks before closing EACH parent**
6. Stops recursion when parent has open children
7. **Runs bd sync at end**
8. Stays in scope (no git operations, no "start next task")
9. Handles edge cases (no tasks, deep hierarchy)
10. Does NOT rationalize with patterns above

## Key Insight

**The "Obvious Logic" Trap:**

When logic seems bulletproof ("all children closed → close parent"), agents:
1. Skip asking (logic is "obvious")
2. Skip verification (feels redundant)
3. Skip "obvious" ancillary steps (bd sync)

**Solution:** Make "obvious" steps EXPLICIT and MANDATORY.

"Obvious logic" requires MORE structure, not less.
