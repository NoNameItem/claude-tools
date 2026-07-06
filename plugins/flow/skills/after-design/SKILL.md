---
name: after-design
description: Link a design document to the current beads task after the brainstorming or design phase. Use right after finishing a design doc; it records the link and suggests /flow:decompose, nothing else.
allowed-tools: Bash(bd:*) Bash(ls:*) Bash(head:*)
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
| 2. Find Design | Newest in docs/superpowers/specs/ or docs/plans/ | Recent file |
| 3. **Save Link** | Add `Design: path` to description | **PRIMARY GOAL** |
| 4. Sync | `flow-sync push` | Persist to git |
| 5. Suggest | Offer `/flow:decompose` | If task needs subtasks |

**Total actions:** 2 (save link + sync)
**Total scope:** Save Design link + sync

## THE PRIMARY TASK

```
+--------------------------------------------------+
|                                                  |
|  SAVE THIS TO TASK DESCRIPTION:                  |
|                                                  |
|  Design: docs/superpowers/specs/{design-filename}|
|                                                  |
|  That's the ENTIRE task. Nothing else.           |
|                                                  |
+--------------------------------------------------+
```

## Workflow

Follow these steps **in order**. Do not add steps.

### 0. Require supported bd (version guard)

```bash
flow-require-bd
```

If this exits non-zero, **STOP**: print its stderr message and run no further commands. flow requires `bd >= 1.0.0` — see `plugins/flow/README.md`, section "bd requirements and migration".

### 1. Find In-Progress Leaf Task

```bash
bd list --status=in_progress
```

Filter for leaf tasks (no open children).

**If multiple found:** Ask user which task this design is for.
**If none found:** Suggest running `flow:start` first.

### 2. Find Newest Design Document

```bash
flow-find-doc design
```

Look for the newest markdown file across **both** `docs/superpowers/specs/`
(superpowers 5.x+) and `docs/plans/` (pre-v5). Newest by mtime wins.

**Heuristics:**
- Recent (within last hour)
- Contains "Requirements", "Architecture", "Design"
- User just mentioned finishing design

**If multiple candidates:** Ask user which file.
**If none found:** Ask user for design file path.

### 3. Save Design Link to Description

**This is THE task. The only action.**

First read the task description (`bd show {task-id}`) and look for existing `Design:` lines — match **both** bare `Design:` and labeled `Design (…):`.

**If there is no `Design:` line at all** (labeled or not) — just record it (preserves any `Plan:` line):

```bash
flow-link-doc {task-id} Design {design-path}
```

**If the task already has one or more `Design:` lines** — a design exists, so the new one is either a *rework iteration* (keep the history) or a *fix to the latest design* (overwrite the newest). Ask in **plain text** (never a structured dialog), then wait for the answer:

```
Task already has a design:
  {existing Design lines, newest last}

Is {design-path}:
  1. A new iteration (rework) — keep the old, append the new
  2. A fix to the latest design — replace the newest line

Optional label (helps future readers). Suggestions from this session: {2–3 short labels inferred from context, e.g. rework, fix review issues}. Type one, your own, or leave blank.
```

- **New iteration (1)** → `flow-link-doc {task-id} Design {design-path} --append [--label {label}]`
  (`--append` is a no-op if this exact path is already recorded — an identical path changes nothing.)
- **Fix to latest (2)** → `flow-link-doc {task-id} Design {design-path} --replace-latest [--label {label}]`

Omit `--label` when the user leaves it blank.

### 4. Sync Changes

```bash
flow-sync push
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

       Design: docs/superpowers/specs/2026-02-09-feature-design.md

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

       Design: docs/superpowers/specs/2026-02-09-feature-design.md

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
Task already has a design:
  Design: docs/superpowers/specs/old-design.md

Is docs/superpowers/specs/2026-02-09-new-design.md:
  1. A new iteration (rework) — keep the old, append the new
  2. A fix to the latest design — replace the newest line

Optional label — suggestions: rework, fix review issues (blank to skip): _____
```

### Has Plan, Adding Design

```
Task description before:
  Plan: docs/superpowers/plans/2026-01-17-plan.md

Task description after:
  Design: docs/superpowers/specs/2026-02-09-design.md
  Plan: docs/superpowers/plans/2026-01-17-plan.md

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
