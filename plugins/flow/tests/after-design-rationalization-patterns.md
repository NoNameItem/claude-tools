# Rationalization Patterns for after-design (from Baseline)

## Core Pattern: "Helpful Automation"

**Definition:** Agents skip consultation and preview when user seems to want fast results.

**Manifestations:**
1. "User wants to start asap" → create subtasks immediately
2. "I'll complete the setup" → do extra work beyond scope
3. "Preview is overhead" → skip showing what will be created
4. "Confirmation slows down" → bypass approval step

## Specific Rationalizations Observed

### 1. "User Wants to Start ASAP"
**When:** Time pressure present ("I need to start implementing asap")
**Why it happens:** "asap" signals urgency
**Problem:** Urgency ≠ skip consultation; user still needs to see what's being created
**Counter needed:** Explicit requirement to show preview even under time pressure

### 2. "I'll Complete the Setup"
**When:** User asks for one thing, agent does several
**Why it happens:** Agent wants to be maximally helpful
**Problem:** Scope creep - each skill should do ONE thing well
**Counter needed:** Clear scope boundaries - what this skill does and doesn't do

### 3. "Just Creating Subtasks"
**When:** Agent assumes subtask structure from design
**Why it happens:** Design has clear structure, seems obvious
**Problem:** User might want to review/adjust before creating
**Counter needed:** Always show preview, even if structure is clear

### 4. "No Existing Subtasks to Check"
**When:** Agent doesn't look for existing subtasks
**Why it happens:** Assumes fresh state
**Problem:** If run twice, creates duplicates
**Counter needed:** Explicit merge logic - check existing, skip duplicates

## Pressure Amplification

| Pressure Type | Effect | Example |
|---------------|--------|---------|
| Time | Skip preview/confirmation | "User said asap" |
| Authority | Do exactly what stated | "User asked to run workflow" |
| Helpfulness | Add extra work | "I'll set up branch too" |
| Efficiency | Skip "obvious" steps | "Structure is clear from design" |

**Key insight:** Pressure causes skipping steps that feel like "overhead" but are actually core service.

## What Skill Must Counter

### 1. Explicit Workflow Steps
1. Find in_progress leaf task
2. Find newest design doc
3. Parse subtasks from design
4. **Show preview** (with format, dependencies)
5. **Ask confirmation** (explicit yes/no)
6. Check existing subtasks (merge logic)
7. Create new subtasks only
8. Save design path to description

### 2. Preview Format Needed
```
Found 5 subtasks in design:

1. claude-tools-xxx.1: Implement input component
   - React component for user input
   - Form validation
   - Priority: P3 (inherits from parent)

2. claude-tools-xxx.2: Add data validation
   ...

Dependencies: All depend on parent (claude-tools-xxx)

Should I create these 5 subtasks? (yes/no)
```

### 3. Scope Boundaries
**This skill does:**
- Find task and design
- Parse subtasks
- Show preview
- Create subtasks after confirmation
- Save design path

**This skill does NOT:**
- Create git branches (use flow:start or manual)
- Commit files (separate workflow)
- Run tests (separate workflow)
- Update status to in_progress (flow:start handles this)

### 4. Merge Logic
```
Checking existing subtasks...

Found 2 existing:
- claude-tools-xxx.1: Implement input component (exists)
- claude-tools-xxx.2: Add data validation (exists)

From design (5 total):
✓ Skip: Implement input component (exists)
✓ Skip: Add data validation (exists)
+ New: Create storage layer
+ New: Write integration tests
+ New: Update documentation

Should I create these 3 new subtasks? (yes/no)
```

### 5. Red Flags to Include
- "User said asap"
- "I'll complete the setup"
- "Structure is clear from design"
- "No need to show preview"
- "Confirmation is overhead"
- "I'll just do it"

All mean: STOP. Follow the workflow.

### 6. Rationalization Table Entries

| Excuse | Reality |
|--------|---------|
| "User wants to start asap" | Preview takes 5 seconds. Fixing wrong subtasks takes 5 minutes. |
| "I'll complete the setup" | Scope creep. One skill, one job. |
| "Structure is clear from design" | User might want to adjust. Always show preview. |
| "No existing subtasks" | Check anyway. Merge logic prevents duplicates. |
| "Confirmation slows things down" | Creating wrong things is slower than confirming right things. |
| "This is being helpful" | Assuming isn't helpful - consulting is. |

## Expected Skill Structure

Based on patterns, skill needs:
1. **Overview** with core principle
2. **Quick reference** table
3. **Explicit workflow** (8 steps)
4. **Preview format** (example)
5. **Merge logic** (with example)
6. **Scope boundaries** (does/doesn't)
7. **Red flags** list
8. **Rationalization table**
9. **Examples** (good vs bad)

## Success Criteria for GREEN Phase

Agent passes when it:
1. Finds task and design correctly
2. Parses subtasks heuristically
3. **Shows preview** with all details
4. **Asks for confirmation** explicitly
5. Checks existing subtasks (merge logic)
6. Creates only new subtasks
7. Saves design path
8. Stays in scope (no branch, no commit)
9. Follows workflow even under pressure
10. Does NOT rationalize with patterns above
