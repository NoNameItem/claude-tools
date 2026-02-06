# Sonar Sync Skill Design

## Task

claude-tools-elf.8 — Скилл sonar-sync: синхронизация SonarQube issues с beads

## Overview

Skill `syncing-sonarcloud` in the flow plugin synchronizes SonarQube/SonarCloud issues with beads tasks. Two modes:
main branch (bulk task creation for tech debt review) and PR (fix now or defer as subtasks).

**Command:** `/flow:sonar-sync [project-key] [--pr <id>]`
**Skill:** `plugins/flow/skills/syncing-sonarcloud/SKILL.md`
**Command file:** `plugins/flow/commands/sonar-sync.md`

## Mode Detection

1. If `--pr <id>` passed — PR mode
2. If no `--pr` — run `gh pr view --json number` for current branch
   - PR found — ask: "Found PR #42. Check PR issues or main branch?"
   - No PR — main branch mode

## Shared Steps

### Step 1: Project Selection

If project key passed as argument — use it directly.

Otherwise, call `mcp__sonarqube__search_my_sonarqube_projects` and show numbered list:

```
SonarQube projects:

1. NoNameItem_statuskit (statuskit)
2. NoNameItem_read-comics (read-comics)

Select project (number or key):
```

### Step 2: Issue Loading & Deduplication (Subagent)

Single haiku subagent handles all heavy lifting:

1. Call `mcp__sonarqube__search_sonar_issues_in_projects` with `projects=[key]`, `ps=500`
   - For PR mode: add `pullRequestId=<id>`
   - Paginate if `paging.total > 500`
2. Filter: keep only `status == "OPEN"`
3. Sort by severity: BLOCKER > HIGH > MEDIUM > LOW > INFO
4. Deduplicate: run `bd list --desc-contains "SonarQube Key:" --json`, extract existing keys, remove matches
5. Return first 100 new issues + stats

**Subagent return format:**
```
Total issues: 47, open: 12, already in beads: 3, new: 9

New issues (1-9 of 9):
1|AZwAbUFA...|BLOCKER|pythonsecurity:S2083|src/statuskit/setup/gitignore.py|62|Change this code to not construct the path from user-controlled data.
2|AZv5-iSv...|CRITICAL|python:S3776|src/statuskit/modules/model.py|70|Refactor this function to reduce its Cognitive Complexity from 18 to the 15 allowed.
...
```

If new > 100: `Shown 100 of 234 new. Load next 100?`

## Main Branch Mode

### Step 3a: Find Parent Task

Search beads for Sonar-related tasks:

```bash
bd list --desc-contains "SonarQube" --json
bd list --desc-contains "Sonar" --json
```

Merge results (deduplicate by ID).

**Multiple found:**
```
Found SonarQube-related tasks:

1. [E] StatusKit Sonar Issues (claude-tools-4u3) | P2 · open | #statuskit
2. [T] Read-Comics Sonar Issues (claude-tools-xxx) | P2 · open | #read-comics

Select parent task (number or ID), or 'new' to create:
```

**One found:**
```
Found SonarQube task:
  [E] StatusKit Sonar Issues (claude-tools-4u3) | P2 · open | #statuskit

Use as parent? (yes / other / new)
```

**None found:**
```
No SonarQube-related tasks found.

1. Create new parent task
2. Specify existing task by ID

Your choice:
```

Creating new parent — ask:
- Title (suggest `{project-name} Sonar Issues`)
- Parent epic (show open epics or skip)
- Type: epic (default)

### Step 4a: Preview Table

```
New SonarQube issues (9):

| #  | Severity | Type  | File                          | Line   | Message                              |
|----|----------|-------|-------------------------------|--------|--------------------------------------|
| 1  | BLOCKER  | bug   | setup/gitignore.py            | 62     | Path traversal from user-controlled  |
| 2  | CRITICAL | chore | modules/model.py              | 70     | Cognitive Complexity 18 > 15         |
| 3  | CRITICAL | chore | core/config.py                | 10     | Duplicating literal ".claude" 4x     |
...

Already in beads: 3 | Skipped (not OPEN): 35
```

"Type" column — preliminary classification:
- `security` in rule OR severity=BLOCKER — **bug**
- Everything else — **chore**

**Selection:**
```
What to create?
- Enter or 'all' — create all 9
- Numbers comma-separated — create selected (e.g., 1,3,5)
- 'n' — skip all
```

### Step 5a: Task Creation

For each selected issue — `bd create --parent <parent-id>`:

**Classification:**

| Condition | Type | Priority | Label |
|-----------|------|----------|-------|
| `security` in rule OR severity=BLOCKER | bug | P0 | — |
| Everything else | chore | P2 | refactoring |

**Title:** `{short message} ({filename})`
- Truncate message to ~60 chars
- Example: `Reduce Cognitive Complexity (model.py)`

**Description:**
```
**SonarQube Key:** AZwAbUFA...
**Rule:** python:S3776
**Link:** https://sonarcloud.io/project/issues?id=NoNameItem_statuskit&open=AZwAbUFA...
**File:** src/statuskit/modules/model.py
**Lines:** 70

**Message:** Refactor this function to reduce its Cognitive Complexity from 18 to the 15 allowed.
```

Create sequentially (parallel `bd create` may conflict with SQLite).

### Step 6a: Report

```
Created: 7
  - bug (P0): 1
  - chore (refactoring): 6

Skipped (already in beads): 3
Skipped (user): 2
```

If issues remain (batch > 100):
```
134 new issues remaining.

1. Load next 100
2. Stop

Your choice:
```

## PR Mode

### Step 3b: Find Parent Task

Check session context first — current in_progress task from flow:start/flow:continue.

```
Current task: [F] Add git module (claude-tools-c7b) | in_progress

Create subtasks under claude-tools-c7b? (yes / other)
```

If no task in context — fallback: extract task ID from branch name
(`feature/claude-tools-c7b-git-module` → `claude-tools-c7b`).

### Step 4b: Preview Table

Same format as main branch mode.

### Step 5b: Action Selection

```
What to do with these issues?
- Numbers to fix now (e.g., 1,2,3)
- Numbers to create subtasks (e.g., 4,5)
- 'all fix' — fix all now
- 'all task' — create subtasks for all
- 'n' — skip
```

**Fix now:** For each selected issue — read file, show problem, propose and apply fix, commit.

**Create subtasks:** Same as main branch creation, but parent = current task.
Classification and description format identical to main branch mode.

### Step 6b: Report

```
Fixed in session: 3
Created subtasks: 2

Skipped (already in beads): 0
Skipped (user): 0
```

## Mode Comparison

|  | Main Branch | PR |
|---|---|---|
| **Trigger** | No PR on current branch, or explicit choice | `--pr <id>` or autodetect |
| **Project** | Argument or pick from list | Argument or pick from list |
| **Parent** | Search by "Sonar" in beads / create new | Current task from context / branch name |
| **Loading** | Subagent: all pages, OPEN, dedup, batch 100 | Subagent: PR issues, OPEN, dedup |
| **Preview** | Table with classification | Table with classification |
| **Action** | Create beads tasks | Fix now AND/OR create subtasks |
| **Report** | Creation stats | Fixes + created subtasks stats |

## SonarCloud URL

Hardcoded `https://sonarcloud.io` for now. Configurable base URL deferred to future iteration.

## Out of Scope

- Auto-detection of SonarQube project from repo
- Grouping similar issues
- Dry-run mode
- Severity filtering on input
- Updating existing beads tasks from SonarQube
- Self-hosted SonarQube base URL configuration
