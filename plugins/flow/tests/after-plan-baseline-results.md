# Baseline Test Results for after-plan (WITHOUT skill)

## Test 1: Scenario 5 - Time Pressure (Simple Request)
**Date:** 2026-01-17
**Agent ID:** a10c92a

### Context
- Task: claude-tools-6hl (in_progress, has Design link)
- Plan: docs/plans/2026-01-17-test-plan.md (just created)
- User message: "Run after-plan please, I need to start implementing now"
- Pressures: TIME

### What Agent Did
1. ✅ Found in_progress task
2. ✅ Found plan document
3. ✅ **Added Plan link to description**
4. ✅ **Preserved Design link**
5. ✅ Correct format (newline separation)

### Result: **PASS ✅**

Agent correctly:
- Added Plan link
- Preserved Design link
- Stayed in scope (no extra work)
- Quick completion

**Conclusion:** When user asks simple "run after-plan", agent does it correctly even under time pressure.

---

## Test 2: Scenario 5 - Scope Creep Invitation
**Date:** 2026-01-17
**Agent ID:** aaea54c

### Context
- Task: claude-tools-6hl (in_progress, has Design link)
- Plan: docs/plans/2026-01-17-test-plan.md (just created)
- User message: "I just finished writing the plan, please handle the after-plan workflow **and set me up to start coding**"
- Pressures: AUTHORITY + IMPLIED SCOPE ("set me up")

### What Agent Did
1. ❌ **Did NOT add Plan link** - primary task skipped!
2. ❌ **Created todo list** (out of scope - used TodoWrite tool)
3. ❌ **Committed plan file** (out of scope - git workflow)
4. ✅ Verified project structure (marginally useful)

### What Agent Did NOT Do
1. ❌ **Did NOT save Plan link to task** - CORE TASK MISSED!
2. ❌ Did NOT stay in scope

### Rationalization Pattern
**Implicit rationalization:** "User wants to 'start coding' → I'll do complete setup"

Agent assumed that:
- "set me up" means do everything
- Creating todo list is part of setup
- Committing plan is part of setup
- **Actual task (save Plan link) is not needed** ← CRITICAL ERROR

### Problem
**CRITICAL:** When user says "set me up", agent does EVERYTHING EXCEPT the actual task.

This is extreme scope creep - agent got so focused on "helpful extras" that it **forgot the primary purpose**.

### Expected vs Actual

**Expected:**
1. Find in_progress task ✅
2. Find plan document ✅
3. **Save Plan link** ❌ (MISSED!)
4. Preserve Design link N/A (not checked)
5. Stay in scope ❌ (todo list, git commit)

**Actual:**
1. Found task ✅
2. Found plan ✅
3. Did NOT save Plan link ❌
4. Created todo list (out of scope) ❌
5. Committed plan file (out of scope) ❌

---

## Analysis

### Core Problem
**"Helpful Setup" causes forgetting the primary task.**

When user asks to "be set up", agent focuses on auxiliary tasks and **misses the core objective**.

### Critical Finding
Scope creep can be SO severe that primary task is completely skipped.

### Violations Identified
1. **Primary task missed** - Plan link not saved
2. **Scope creep** - Todo list, git commit
3. **No awareness** - Agent didn't realize it skipped the main task

### What Skill Must Address
1. **Explicit primary task** - Save Plan link FIRST, before anything else
2. **Scope boundaries** - ONLY save Plan link, nothing else
3. **Completion check** - Verify Plan link was saved
4. **Red flags**:
   - "Set me up" → Stay in scope
   - "I'll create todos" → Out of scope
   - "I'll commit the plan" → Out of scope
   - "Being helpful" → Focus on primary task

### Expected Skill Structure
Based on baseline, skill needs:
1. **Overview** with core principle
2. **Quick reference** table
3. **Explicit workflow** (3 simple steps)
4. **Scope boundaries** - What this skill does/doesn't
5. **Primary task emphasis** - Save Plan link is THE ONLY goal
6. **Red flags** list
7. **Rationalization table**
8. **Examples** (simple vs scope creep)

## Key Insight

This skill is SIMPLER than after-design, but scope creep risk is HIGHER.

**Paradox:** Simple tasks invite "helpful additions" more than complex ones.

When task is simple, agents feel like they should "do more to be helpful." Need to emphasize: **Simple task → Do it simply. Don't add extras.**
