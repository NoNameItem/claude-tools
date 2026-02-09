---
name: decomposing-task
description: Use when user wants to break down a beads task into subtasks based on a design document. Triggered by /flow:decompose or when user says "decompose", "break down task", "create subtasks from design".
---

# Flow: Decompose Task

## Overview

**Core principle:** Dialogue over dictation.

This skill decomposes a task into subtasks through collaborative discussion. The agent proposes decomposition approaches, the user chooses, and together they iterate until the subtask list is right. Always show the full picture on every iteration.

**This skill does ONE thing:** create subtasks from a design document. It does not link designs, commit code, update statuses, or create branches.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Find Task | Get in_progress leaf task | From context or `bd list` |
| 2. Find Design | From `Design:` link or ask | Read the document |
| 3. **Discuss Approach** | Propose 2-3 decomposition options | User chooses, not agent |
| 4. **Form Subtask List** | Build list with attributes | Full preview every iteration |
| 5. **Merge** | Check existing subtasks | Skip duplicates |
| 6. **Create** | Only after explicit confirmation | `bd create` for each |
| 7. **Record** | Write Decomposition section | Append to design doc |
| 8. Sync | `bd sync` | Persist changes |

## Workflow

Follow these steps **in order**. Do not skip steps.

### 1. Find Task and Design Document

**Find the task:**
1. Check conversation context — if a task was selected (after `flow:start`), use it.
2. If not — `bd list --status=in_progress`, find leaf task (no open children).
3. If multiple — ask which one.
4. If none — suggest `flow:start` first.

**Find the design document:**
1. Read task description, look for `Design: docs/plans/...` line.
2. If no link — ask user for the document path.
3. Read the design document fully.

### 2. Discuss Decomposition Approach

**Do NOT jump straight to listing subtasks.** First, propose 2-3 decomposition approaches based on what you see in the design. Each approach is a principle + 2-3 example subtasks.

Example approaches:
- **By component/module:** One subtask per system component
- **By implementation stage:** Data layer → logic → interface
- **By user scenario:** Each user-facing flow is a subtask
- **By architectural layer:** Model → service → API → UI

**Format:**

```
Based on the design, I see these decomposition options:

1. By component:
   - Skill SKILL.md creation
   - Command entry point
   - Plugin registration

2. By implementation stage:
   - Extract logic from existing skill
   - Build new skill
   - Wire up and test

3. Your own approach

Which approach works best? Or suggest your own:
```

**Wait for user to choose.** Do not pick for them, even if one seems "obviously right."

### 3. Form Subtask List

Based on the chosen approach, build the full subtask list. For each subtask determine:

| Attribute | How to determine |
|-----------|-----------------|
| Title | From content (required) |
| Description | 1-3 sentences (optional) |
| Type | By content (see table below) |
| Priority | Inherit from parent |
| Labels | From parent + by content (see rules below) |

**Type by content:**

| Content | Type |
|---------|------|
| Bug fix | bug |
| New functionality, adding capability | feature |
| Tech work (CI/CD, linters, infra), refactoring | chore |
| Documentation, everything else | task |

**Labels:**
- Always copy parent's labels.
- Add content-specific labels: `#ci`, `#infra`, `#docs`, `#api`, `#cli`, `#config`, etc.

**Preview format (show on EVERY iteration):**

```
Subtasks for claude-tools-xxx (parent: "Task Title"):

1. [F] Feature name | P3 | #flow — description
2. [C] Refactoring module | P3 | #flow #infra — description
3. [B] Fix validation | P3 | #flow #config — description
4. [T] Update docs | P3 | #flow #docs — description

Type legend: [F]=feature [B]=bug [C]=chore [T]=task

What to change, or approve to proceed?
```

**On each user correction, show the FULL updated list — not just the diff.** User must always see the complete picture.

Iterate until user says "approve", "ok", "create them", "go ahead", or similar.

### 4. Merge with Existing Subtasks

**Before creating, check what already exists:**

```bash
bd show {parent-id}
```

For each proposed subtask:

| Match | Action |
|-------|--------|
| Exact match (title identical) | Skip |
| >80% title similarity | Ask user |
| No match | Create |

**Show merge preview:**

```
Subtasks to create:
1. [F] New feature | P3 | #flow — description
2. [C] Refactoring | P3 | #flow — description

Skipped (already exist):
- claude-tools-xxx: Existing task (exact match)

Needs clarification:
- "Update plugin config" ≈ existing "Modify plugin.json" (82% similar)
  → Create new / Skip / Merge?

Create 2 subtasks?
```

### 5. Create Subtasks

**Only after explicit "yes" / "create" / "go ahead":**

```bash
bd create --title="..." --description="..." --type=feature --priority=P3 --parent={parent-id} --label=flow
```

For each subtask. Show progress:

```
Creating subtasks...
+ Created claude-tools-xxx.1: Feature name
+ Created claude-tools-xxx.2: Refactoring module
+ Created claude-tools-xxx.3: Update docs

Created 3 subtasks under claude-tools-xxx.
```

### 6. Record Decomposition in Design Document

Append a `## Decomposition` section to the end of the design document:

```markdown
## Decomposition

1. **Feature name** (claude-tools-xxx.1) — description
2. **Refactoring module** (claude-tools-xxx.2) — description
3. **Update docs** (claude-tools-xxx.3) — description
```

```bash
# Append to design doc (use Edit tool, not echo)
# Then:
git add docs/plans/...
git commit -m "docs(flow): add decomposition to design doc"
```

### 7. Sync

```bash
bd sync
```

## Scope Boundaries

### This Skill DOES:
- Find in_progress task and its design document
- Discuss decomposition approach with user
- Build subtask list with correct attributes
- Show full preview on every iteration
- Merge with existing subtasks
- Create subtasks after explicit confirmation
- Record decomposition in design document
- Sync changes

### This Skill Does NOT:
- Link design documents (use `flow:after-design`)
- Create branches (use `flow:start`)
- Commit code files
- Update task status
- Run tests or builds
- Implement any code

**If user asks for out-of-scope work:**
Redirect. "That's handled by `flow:after-design` / `flow:start` / separate workflow."

Do NOT do it "because the user explicitly asked." Scope is scope.

## Red Flags - STOP

If you're thinking any of these, STOP:

- "Design already provides the decomposition, no need to discuss approach"
- "I'll just list subtasks directly from the design sections"
- "User is in a hurry, skip the approach discussion"
- "I'll also commit the design doc changes"
- "Let me update the task status too"
- "I'll link the design while I'm at it"
- "Type is obvious, no need to check the rules table"
- "Labels from parent are enough, skip content-specific ones"
- "User made a correction, I'll just show the diff"
- "They said 'ok' to corrections, that means 'create them'"

**All of these mean: Go back to the workflow. Follow every step.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Design already decomposes the work" | Design describes WHAT. Decomposition approach is HOW to split it into tasks. Different approaches yield different subtask structures. |
| "User is in a hurry" | Approach discussion takes 30 seconds. Wrong subtask structure costs 30 minutes. |
| "Type is obvious from context" | Use the rules table. "Obvious" leads to inconsistent types across tasks. |
| "User asked to commit too" | Out of scope. Redirect to separate workflow. Doing extra != being helpful. |
| "Correction implies approval" | Correction means "change this." Approval is explicit "create them." Different speech acts. |
| "Showing full list is redundant" | User forgets details between iterations. Full list = full context = fewer mistakes. |
| "I'll pick the best approach" | User agency. Even if you're 95% sure, ask. |
| "No existing subtasks to merge" | Check anyway. Prevents duplicates if workflow runs twice. |

## Examples

### BAD: Skip approach discussion

```
User: "Decompose task based on the design doc"
Agent: Based on the design, here are 4 subtasks:
       1. [F] Create SKILL.md | P3 | #flow
       2. [T] Create command | P3 | #flow
       ...
       Create them?
```

**Problem:** Jumped straight to listing. Different decomposition approaches yield different structures.

### GOOD: Discuss approach first

```
User: "Decompose task based on the design doc"
Agent: I've read the design. Here are decomposition options:

       1. By deliverable:
          - New decomposing-task skill
          - Simplified linking-design skill
          - Command + plugin registration

       2. By implementation order:
          - Extract subtask logic from linking-design
          - Build new skill from extracted logic
          - Wire up command and register

       3. Your own approach

       Which works best?

User: 1

Agent: Subtasks for claude-tools-elf.9 (parent: "Decompose skill"):

       1. [F] Create decomposing-task skill | P3 | #flow — New SKILL.md with full workflow
       2. [C] Simplify linking-design skill | P3 | #flow — Remove subtask creation, keep only design linking
       3. [T] Add decompose command entry point | P3 | #flow — commands/decompose.md
       4. [C] Update plugin.json registration | P3 | #flow — Register new skill, bump version

       What to change, or approve?
```

### BAD: Scope creep on explicit request

```
User: "Decompose the task. Also commit the design and update status."
Agent: [Creates subtasks, commits design doc, runs bd update --status]
```

**Problem:** Did out-of-scope work because user "explicitly asked."

### GOOD: Redirect out-of-scope requests

```
User: "Decompose the task. Also commit the design and update status."
Agent: I'll decompose the task into subtasks.

       For committing the design doc — that's a separate git workflow.
       For updating task status — use `bd update` or `flow:start`.

       Let me focus on decomposition. I've read the design...
       [proceeds with approach discussion]
```

### BAD: Show only diff after correction

```
User: "Merge 2 and 3 into one"
Agent: Updated:
       2. [C] Simplify and register plugin | P3 | #flow

       Create them?
```

**Problem:** User lost context of full list. What were 1 and 4?

### GOOD: Show full list after correction

```
User: "Merge 2 and 3 into one"
Agent: Subtasks for claude-tools-elf.9:

       1. [F] Create decomposing-task skill | P3 | #flow — New SKILL.md with full workflow
       2. [C] Simplify linking-design and update registration | P3 | #flow — Remove subtask creation, register new skill
       3. [T] Add decompose command entry point | P3 | #flow — commands/decompose.md

       What to change, or approve?
```

## Edge Cases

### No Design Document Found

```
Task claude-tools-xxx has no Design: link in description.

Please provide the design document path, or describe the task structure for manual decomposition:
```

### Task Already Has Subtasks

Run merge logic (Step 4). Show which will be skipped vs created.

### User Wants Zero Subtasks

```
User: "This is atomic, no subtasks needed"
Agent: Got it. No subtasks created. Task stays as-is.
```

### Design Has Multiple Possible Decomposition Sections

Focus on the design's high-level structure, not on sections like "Implementation Steps" which describe process, not task structure.

## The Bottom Line

Decomposition is a dialogue. Propose approaches, let the user choose, show the full picture on every iteration, stay in scope, and create only after explicit confirmation.

One skill, one job: create subtasks. Everything else is someone else's workflow.
