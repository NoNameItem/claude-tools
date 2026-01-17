# Rationalization Patterns for after-plan (from Baseline)

## Core Pattern: "Helpful Setup Syndrome"

**Definition:** When task is simple, agents add "helpful extras" and may forget the primary task entirely.

**Manifestations:**
1. "User wants to start coding → I'll create todo list"
2. "I should commit the plan → helps with tracking"
3. "Let me set up everything → be maximally helpful"
4. **"I did helpful things → task is complete"** (even though primary task skipped!)

## Specific Rationalizations Observed

### 1. "Set Me Up Means Do Everything"
**When:** User says "set me up to start coding"
**Why it happens:** "Setup" seems to invite comprehensive preparation
**Problem:** Primary task (save Plan link) gets forgotten in the "setup"
**Counter needed:** Explicit scope - ONLY save Plan link, nothing else

### 2. "Simple Task Needs Extras"
**When:** Core task is very simple (just save a link)
**Why it happens:** Feels too simple, agent wants to add value
**Problem:** "Adding value" = scope creep + forgetting core task
**Counter needed:** Emphasize that simple ≠ incomplete

### 3. "Todos Will Help User"
**When:** Plan has implementation steps
**Why it happens:** Agent sees steps, thinks "I should track these"
**Problem:** TodoWrite is separate tool/workflow, not after-plan's job
**Counter needed:** Clear scope boundary - no todos, no task breakdown

### 4. "Committing Plan Is Good Practice"
**When:** Plan file is newly created
**Why it happens:** Agent thinks version control is good practice
**Problem:** Git workflow is separate, not after-plan's concern
**Counter needed:** Scope boundary - no git operations

### 5. "I Did Helpful Things, Task Complete"
**When:** Agent does auxiliary work
**Why it happens:** Feels like progress was made
**Problem:** Primary task skipped, but agent thinks it's done
**Counter needed:** Completion check - verify Plan link was actually saved

## Pressure Amplification

| Pressure Type | Effect | Example |
|---------------|--------|---------|
| "Set me up" | Invites scope creep | Todos, commits, structure checks |
| Simple task | Invites additions | "Too simple, add extras" |
| Authority | Skip verification | "User wants action, not checking" |
| Helpfulness | Forget core task | Focus on auxiliary work |

**Key insight:** Simple task + "setup" language = maximum scope creep risk.

## What Skill Must Counter

### 1. Primary Task Emphasis
**THE ONLY GOAL:** Save `Plan: docs/plans/...` to task description.

Nothing else. That's it. Don't add extras.

### 2. Explicit Workflow Steps
1. Find in_progress leaf task
2. Find newest plan document
3. **Save Plan link to description**
4. Done.

(4 steps total, #3 is the only action)

### 3. Scope Boundaries - Crystal Clear

**This skill DOES:**
✅ Find task
✅ Find plan file
✅ Save Plan link to description
✅ Preserve existing Design link

**This skill Does NOT:**
❌ Create todo lists (use TodoWrite separately)
❌ Commit plan file (use git workflow)
❌ Create subtasks (use after-design)
❌ Update task status (use flow:start)
❌ Create branches (use flow:start)
❌ Parse plan content
❌ Verify project structure
❌ Set up development environment
❌ Start implementation

**One task: Save the link. That's all.**

### 4. Completion Check
After workflow, agent must verify:
- [ ] Plan link in task description?
- [ ] Design link still there (if was there)?
- [ ] No extra work done?

### 5. Red Flags to Include
- "User wants to start coding"
- "Let me set everything up"
- "I'll create todos from the plan"
- "I should commit the plan file"
- "This task is too simple"
- "I'll add extra value"
- "Being maximally helpful"

All mean: STOP. Just save the link. Nothing else.

### 6. Rationalization Table Entries

| Excuse | Reality |
|--------|---------|
| "User wants setup" | Setup = save Plan link. Not todos or commits. |
| "Task is too simple" | Simple is good. Do it simply. Don't add extras. |
| "I'll create todos to help" | TodoWrite is separate workflow. Out of scope. |
| "Committing plan is good practice" | Git workflow is separate. Out of scope. |
| "I did helpful things" | Did you save Plan link? If no, task not done. |
| "Being maximally helpful" | Maximal help = doing THE task, not extras. |

## Expected Skill Structure

Based on patterns, skill needs to be VERY explicit about scope:

1. **Overview** - "Save Plan link. That's all."
2. **Quick reference** - 4 steps, only #3 is action
3. **Scope boundaries** - Large "Does NOT" list
4. **Primary task box** - Big, obvious, can't miss
5. **Completion check** - Verify link was saved
6. **Red flags** - All "helpful" rationalizations
7. **Rationalization table** - Excuse → Reality
8. **Examples** - Simple vs scope creep

## Success Criteria for GREEN Phase

Agent passes when it:
1. Finds task and plan
2. **Saves Plan link** (PRIMARY GOAL)
3. Preserves Design link
4. **Does NOTHING else**
5. Verifies link was saved
6. Does NOT create todos
7. Does NOT commit files
8. Does NOT add "helpful extras"
9. Completes quickly and simply
10. Does NOT rationalize with patterns above

## Key Insight

**Paradox of Simple Tasks:**

Complex tasks → Agents follow workflow carefully
Simple tasks → Agents add "helpful extras" and may forget core task

**Solution:** For simple tasks, emphasize simplicity even more strongly.

"This task is simple. Do it simply. Don't add extras."
