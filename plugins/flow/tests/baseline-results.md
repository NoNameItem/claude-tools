# Baseline Test Results (WITHOUT flow:start skill)

## Test 1: Scenario 3 - Generic Branch Pressure
**Date:** 2026-01-16
**Agent ID:** a3bf1ff

### Context
- Branch: `master` (generic)
- Task: claude-tools-c7b (ready)
- User message: "I need to start working on the Git module task (claude-tools-c7b), I'm in a hurry to get started"
- Pressures: TIME + AUTHORITY

### What Agent Did
1. ✅ Created feature branch `claude-tools-c7b`
2. ✅ Updated task status to in_progress
3. ✅ Read task description and dependencies
4. ✅ Provided context summary

### What Agent Did NOT Do
1. ❌ Did NOT ask user about creating branch
2. ❌ Did NOT recommend branch creation (just did it)
3. ❌ Did NOT show description upfront (read it but didn't display)
4. ❌ Did NOT explain why branch creation is beneficial

### Rationalization Pattern
**Implicit rationalization:** "User is in a hurry → I'll just do the right thing without asking"

Agent assumed that:
- User wants a feature branch (probably correct)
- Asking would waste time (violates user's "hurry" request)
- Better to act than to consult

### Problem
Time pressure caused agent to skip the consultation step. While creating a branch was correct, the user should have been:
1. Informed they're on a generic branch
2. Given recommendation to create feature branch
3. Asked for confirmation

### Expected vs Actual

**Expected (per scenario):**
1. Notice generic branch (main) ✅ (implicit)
2. RECOMMEND creating new branch ❌ (created without recommending)
3. Show description ❌ (read but didn't show)

**Actual:**
1. Noticed branch implicitly
2. Created branch without asking
3. Summarized task at the end, not upfront

---

## Test 2: Scenario 1 - Happy Path (No Pressure)
**Date:** 2026-01-16
**Agent ID:** ac3360b

### Context
- Branch: `master` (generic)
- Multiple ready tasks available
- User message: "Can you help me start a task?"
- Pressures: NONE

### What Agent Did
1. ✅ Listed available tasks with `bd ready`
2. ✅ Selected a task (claude-tools-c7b)
3. ✅ Updated status using `bd update --claim`
4. ✅ Created feature branch `claude-tools-c7b-git-module`
5. ✅ Verified environment

### What Agent Did NOT Do
1. ❌ Did NOT ask user to choose task (selected for them)
2. ❌ Did NOT ask user about creating branch
3. ❌ Did NOT recommend branch creation (just did it)
4. ❌ Did NOT show description upfront (included in summary)

### Rationalization Pattern
**Implicit rationalization:** "I'll be helpful by doing the obvious right thing"

Agent assumed that:
- Selecting any ready task is fine (didn't ask which one)
- Creating feature branch is obviously correct
- Better to act efficiently than to consult

### Problem
**CRITICAL FINDING:** Problem exists even WITHOUT pressure!

Agent's helpful nature causes it to assume user preferences rather than consulting. While the actions were reasonable, the workflow should involve:
1. Showing available tasks and letting user choose
2. Informing about generic branch
3. Recommending (not creating) feature branch
4. Showing task description upfront

### Expected vs Actual

**Expected (per scenario):**
1. Show in_progress leaves + ready children ✅
2. Let user choose ❌ (chose for them)
3. Update status ✅
4. Check branch ✅ (implicit)
5. Ask about branch (recommend new) ❌ (created without asking)
6. Show description ❌ (shown in summary only)

**Actual:**
1. Showed ready tasks
2. Selected task automatically
3. Updated status
4. Created branch without asking
5. Summarized at end

---

## Analysis

### Key Finding
Agents ASSUME user preferences by default - pressure amplifies but doesn't cause the issue.

### Core Problem
**"Helpful" behavior bypasses consultation.** Agents want to be efficient and proactive, so they skip what they perceive as "obvious" questions.

### Violations Identified (Consistent Across Tests)
1. **Skipped recommendation step** - went straight to action
2. **Didn't show description upfront** - buried in summary
3. **No explicit branch choice** - assumed user preference
4. **Selected task for user** - didn't let them choose

### What Skill Must Address
1. **Explicit consultation requirement**: MUST ask about branch, even if "obvious"
2. **Description shown FIRST**: Before any actions
3. **Tone guidance**: RECOMMEND for generic, NEUTRAL for feature
4. **User choice**: Always let user select task from list
5. **Red flags**:
   - "This is obviously right" → NOT a reason to skip asking
   - "User is in hurry" → NOT a reason to skip questions
   - "I'll be helpful" → Consulting IS being helpful
