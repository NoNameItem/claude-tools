---
name: linking-design
description: Use after completing brainstorming/design phase. Links design document to task. Simple operation — save the link, nothing else. Suggests /flow:decompose for subtask creation.
---

# Flow: After Design

## Overview

**Core principle:** Save the link. That's all.

This is a SIMPLE task. Find design document, save link to task description. Done.

**Do NOT add "helpful extras".** This skill does exactly one thing: save Design link. Nothing more.

**Subtask creation moved to `/flow:decompose`.** If user wants to break task into subtasks, suggest running that command after this one.

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 1. Find Task | Get in_progress leaf task | Ask if multiple |
| 2. Find Design | Newest in docs/plans/ | Recent file |
| 3. **Save Link** | Add `Design: path` to description | **PRIMARY GOAL** |
| 4. Sync | `bd sync` | Persist to git |
| 5. Suggest | Offer `/flow:decompose` | If task needs subtasks |

**Total actions:** 2 (save link + sync)
**Total scope:** Save Design link + sync

## THE PRIMARY TASK

```
+--------------------------------------------------+
|                                                  |
|  SAVE THIS TO TASK DESCRIPTION:                  |
|                                                  |
|  Design: docs/plans/{design-filename}            |
|                                                  |
|  That's the ENTIRE task. Nothing else.           |
|                                                  |
+--------------------------------------------------+
```

## Workflow

Follow these steps **in order**. Do not add steps.

### 1. Find In-Progress Leaf Task

```bash
bd list --status=in_progress
```

Filter for leaf tasks (no open children).

**If multiple found:** Ask user which task this design is for.
**If none found:** Suggest running `flow:start` first.

### 2. Find Newest Design Document

```bash
ls -t docs/plans/*.md | head -1
```

Look for newest markdown file in `docs/plans/`.

**Heuristics:**
- Recent (within last hour)
- Contains "Requirements", "Architecture", "Design"
- User just mentioned finishing design

**If multiple candidates:** Ask user which file.
**If none found:** Ask user for design file path.

### 3. Save Design Link to Description

**This is THE task. The only action.**

Get current description:
```bash
bd show {task-id}
```

Add Design link:
```bash
bd update {task-id} --description="{current-description}\n\nDesign: docs/plans/{design-filename}"
```

**IMPORTANT:**
- Preserve existing content
- **Preserve existing Plan link** (if present)
- Add newline before Design link
- Format: `Design: docs/plans/...`

**If Design link already exists:**
Ask: "Task already has Design link: {old-link}. Update to {new-link}? (yes/no)"

### 4. Sync Changes

```bash
bd sync
```

Persist the design link to git.

### 5. Suggest Decomposition

After saving the link:

> "Design linked. Want to decompose this task into subtasks? Run `/flow:decompose`."

**Do NOT start decomposition yourself.** Just suggest the command.

## Scope Boundaries - READ THIS CAREFULLY

### This Skill DOES (5 things total):
- Find in_progress leaf task
- Find newest design document
- **Save Design link to task description**
- Preserve existing Plan link
- Sync changes to git

### This Skill Does NOT (Long list - READ IT):
- Create subtasks (use `/flow:decompose`)
- Parse design document for subtasks
- Show subtask previews
- Commit design file to git (separate workflow)
- Create branches (use `flow:start`)
- Update task status (use `flow:start`)
- Create todo lists
- Run builds or tests
- Start implementation

**If user says "also create subtasks":**
Save Design link first. Then suggest: "Run `/flow:decompose` for subtask creation."

## Red Flags - STOP

If you're thinking any of these, STOP and just save the link:

- "Let me parse the design for subtasks"
- "I'll create subtasks while I'm here"
- "User wants to start coding"
- "Let me set everything up"
- "I should commit the design file"
- "This task is too simple"
- "I'll add extra value"
- "Being maximally helpful"

**All of these mean: Save the link. Nothing else. Done.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "User wants subtasks too" | That's `/flow:decompose`. Not this skill. |
| "Design clearly has subtasks" | Not your job. Save link, suggest decompose. |
| "Task is too simple" | Simple is good. Do it simply. |
| "I'll create todos to help" | Out of scope. Save link only. |
| "Committing design is good practice" | Git workflow is separate. Out of scope. |
| "Being maximally helpful" | Maximal help = doing THE task, not extras. |

## Examples

### BAD: Parse subtasks (old behavior)

```
User: "I finished the design"
Agent: Found 5 subtasks in the design:
       1. claude-tools-abc.1: Implement X
       ...
       Create them?
```

**Problem:** Subtask creation is now `/flow:decompose`. This skill only saves the link.

### GOOD: Save link, suggest decompose

```
User: "I finished the design"
Agent: Saved Design link to task claude-tools-abc:

       Design: docs/plans/2026-02-09-feature-design.md

       Done. Want to decompose into subtasks? Run `/flow:decompose`.
```

### BAD: Do both at once

```
User: "After design, also create subtasks"
Agent: [Saves link, then creates 4 subtasks]
```

**Problem:** Out of scope. Save link, redirect to decompose.

### GOOD: Redirect

```
User: "After design, also create subtasks"
Agent: Saved Design link to task claude-tools-abc:

       Design: docs/plans/2026-02-09-feature-design.md

       For subtasks, run `/flow:decompose` next.
```

## Edge Cases

### Multiple In-Progress Tasks

```
Found 2 in_progress leaf tasks:
1. claude-tools-abc: Feature X
2. claude-tools-def: Feature Y

Which task is this design for? (enter 1 or 2, or task ID)
```

### Design Link Already Exists

```
Task already has Design link: docs/plans/old-design.md

Update to new design docs/plans/2026-02-09-new-design.md? (yes/no)
```

### Has Plan, Adding Design

```
Task description before:
  Plan: docs/plans/2026-01-17-plan.md

Task description after:
  Design: docs/plans/2026-02-09-design.md
  Plan: docs/plans/2026-01-17-plan.md

Both links preserved.
```

## The Bottom Line

**This is a simple task. Do it simply.**

1. Find task
2. Find design
3. Save link
4. Sync
5. Suggest `/flow:decompose`

Don't parse subtasks. Don't create tasks. Don't commit files.

Just save the link. That's the entire job.

**Paradox of simple tasks:** They invite complexity. Resist it.

Simple task -> Do it simply -> Be done.
