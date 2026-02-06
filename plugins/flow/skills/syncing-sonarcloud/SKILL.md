---
name: syncing-sonarcloud
description: Use when syncing SonarQube/SonarCloud issues with beads tasks, during tech debt review, or when user invokes /flow:sonar-sync. Handles project selection, issue loading, deduplication, classification, and bulk task creation.
---

# Flow: Sonar Sync

## Overview

**Core principle:** Preview before creating. User selects what to import.

This skill synchronizes SonarQube/SonarCloud issues with beads tasks. Two modes: **main branch** (bulk task creation for tech debt review) and **PR** (fix now or defer as subtasks).

**Command:** `/flow:sonar-sync [project-key] [--pr <id>]`

## Quick Reference

| Step | Action | Key Point |
|------|--------|-----------|
| 0. Mode | Detect main vs PR | `--pr` flag or autodetect |
| 1. Project | Select SonarQube project | Argument or pick from list |
| 2. Load | Subagent: fetch + dedup | Haiku subagent for heavy lifting |
| 3. Parent | Find/create parent task | Mode-specific logic |
| 4. Preview | Show table of new issues | User sees BEFORE creating |
| 5. Select | User picks issues | All, subset, or none |
| 6. Create | `bd create` sequentially | Classification rules apply |
| 7. Report | Summary of actions | Stats + remaining count |

**Mode differences:**

| | Main Branch | PR |
|---|---|---|
| **Parent** | Search "Sonar" in beads | Current task from context |
| **Actions** | Create beads tasks only | Fix now AND/OR create subtasks |
| **SonarQube filter** | All project issues | PR issues only |

## Workflow

Follow these steps **in order**. Do not skip steps.

### 0. Mode Detection

**If `--pr <id>` passed:** PR mode with that ID.

**If no `--pr`:**
```bash
gh pr view --json number 2>/dev/null || echo "NO_PR"
```

- PR found: Ask user: "Found PR #42. Check PR issues or main branch?"
- No PR: Main branch mode.

### 1. Project Selection

**If project key passed as argument:** Use it directly.

**Otherwise:** Call MCP tool to list projects:
```
mcp__sonarqube__search_my_sonarqube_projects()
```

Show numbered list:
```
SonarQube projects:

1. NoNameItem_statuskit (statuskit)
2. NoNameItem_read-comics (read-comics)

Select project (number or key):
```

### 2. Issue Loading & Deduplication (Subagent)

**Use a single haiku subagent** (`subagent_type="general-purpose"`, `model="haiku"`) for all heavy lifting. This keeps the main context clean. The subagent needs access to both MCP tools (SonarQube) and Bash (bd commands), so use `general-purpose` type.

**Subagent prompt:**
```
Run these steps and return results in the specified format:

1. Call mcp__sonarqube__search_sonar_issues_in_projects with projects=["<project-key>"], ps=500
   {FOR PR MODE: add pullRequestId="<pr-id>"}
   If paging.total > 500, paginate (increment p=2, p=3, etc.) until all fetched.

   Each issue in the response has these fields:
   - issue.key (string, full unique ID like "AZwAbUFA-iU5OvuD2FL1")
   - issue.severity (BLOCKER, HIGH, MEDIUM, LOW, INFO)
   - issue.status (OPEN, CONFIRMED, RESOLVED, CLOSED)
   - issue.rule (e.g., "pythonsecurity:S2083", "python:S3776")
   - issue.component (e.g., "NoNameItem_statuskit:src/statuskit/setup/gitignore.py")
   - issue.message (full description text)
   - issue.textRange.startLine, issue.textRange.endLine (line numbers)

2. Filter: keep only issues where status == "OPEN"

3. Sort by severity: BLOCKER > HIGH > MEDIUM > LOW > INFO

4. Deduplicate:
   Run: `bd list --desc-contains "SonarQube Key:" --json`
   Parse JSON output. Each beads issue has a "description" field.
   Extract SonarQube keys by finding text after "**SonarQube Key:** " in each description.
   Use FULL keys for comparison (not truncated). Remove any SonarQube issues whose key
   matches an existing beads description.

5. Return EXACTLY this format (first 100 new issues, use FULL keys):

Total issues: <total>, open: <open>, already in beads: <dedup_count>, new: <new_count>

New issues (1-<count> of <new_count>):
<num>|<full_key>|<severity>|<rule>|<component_without_project_prefix>|<startLine>[-<endLine if different>]|<message_truncated_to_80_chars>

To get component without project prefix: strip everything before and including the first ":"
(e.g., "NoNameItem_statuskit:src/foo.py" -> "src/foo.py")

Example line:
1|AZwAbUFA-iU5OvuD2FL1|BLOCKER|pythonsecurity:S2083|src/statuskit/setup/gitignore.py|62|Change this code to not construct the path from user-controlled data.

If new > 100: add line "Shown 100 of <total_new> new issues."
If new == 0: just return the stats line.
```

**If subagent returns 0 new issues:**
```
No new SonarQube issues to import.

Total: <total>, open: <open>, already in beads: <dedup>.
All open issues are already tracked.
```
Stop here.

### 3. Find Parent Task (Mode-Specific)

#### 3a. Main Branch Mode

Search beads for Sonar-related tasks (search both title and description):
```bash
bd list --title-contains "Sonar" --status open --json
bd list --title-contains "Sonar" --status in_progress --json
bd list --desc-contains "SonarQube" --status open --json
bd list --desc-contains "SonarQube" --status in_progress --json
```

Merge all results (deduplicate by ID).

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

Creating new parent - ask:
- Title (suggest `{project-name} Sonar Issues`)
- Parent epic (show open epics or skip)
- Type: epic (default)

#### 3b. PR Mode

Check session context first - current in_progress task from flow:start.

```
Current task: [F] Add git module (claude-tools-c7b) | in_progress

Create subtasks under claude-tools-c7b? (yes / other)
```

If no task in context - fallback: extract task ID from branch name (`feature/claude-tools-c7b-git-module` -> `claude-tools-c7b`).

### 4. Preview Table

Show classified issues in table format. Use the file path as returned by the subagent (project prefix already stripped):

```
New SonarQube issues (9):

| #  | Severity | Type  | File                                  | Line | Message                              |
|----|----------|-------|---------------------------------------|------|--------------------------------------|
| 1  | BLOCKER  | bug   | src/statuskit/setup/gitignore.py      | 62   | Path traversal from user-controlled  |
| 2  | HIGH     | chore | src/statuskit/modules/model.py        | 70   | Cognitive Complexity 18 > 15         |
| 3  | HIGH     | chore | src/statuskit/core/config.py          | 10   | Duplicating literal ".claude" 4x     |
...

Already in beads: 3 | Skipped (not OPEN): 35
```

**"Type" column** - preliminary classification:
- `security` in rule OR severity=BLOCKER -> **bug**
- Everything else -> **chore**

### 5. Action Selection (Mode-Specific)

#### 5a. Main Branch Mode

```
What to create?
- 'all' (or empty input) - create all 9
- Numbers comma-separated - create selected (e.g., 1,3,5)
- 'n' - skip all
```

#### 5b. PR Mode

```
What to do with these issues?
- Numbers to fix now (e.g., 1,2,3)
- Numbers to create subtasks (e.g., 4,5)
- Mixed: "1,2 fix, 3,4 task" - fix some, defer others
- 'all fix' - fix all now
- 'all task' - create subtasks for all
- 'n' - skip
```

**Parsing mixed input:** User may combine in one line: `1 fix, 2,3 task`. Parse by splitting on comma, then checking each token for `fix` or `task` suffix. Numbers without suffix use the most recent action keyword.

**Fix now:** For each selected issue - read file, show problem, propose and apply fix, commit. If fix fails or agent can't determine the fix, inform user and offer to create a subtask instead.

**Create subtasks:** Same as main branch creation, but parent = current task.

### 6. Task Creation

For each selected issue, create a beads task sequentially.

**Classification rules:**

| Condition | Type | Priority | Label |
|-----------|------|----------|-------|
| `security` in rule OR severity=BLOCKER | bug | P0 | - |
| Everything else | chore | P2 | refactoring |

**Title format:** `{short message} ({filename})`
- Truncate message to ~60 chars
- Example: `Reduce Cognitive Complexity (model.py)`

**Description format** (use FULL keys, not truncated):
```
**SonarQube Key:** AZwAbUFA-iU5OvuD2FL1
**Rule:** python:S3776
**Link:** https://sonarcloud.io/project/issues?id=NoNameItem_statuskit&open=AZwAbUFA-iU5OvuD2FL1
**File:** src/statuskit/modules/model.py
**Lines:** 70

**Message:** Refactor this function to reduce its Cognitive Complexity from 18 to the 15 allowed.
```

**Full command templates:**

For bug (security/BLOCKER):
```bash
bd create --title "Path traversal (gitignore.py)" --type bug --priority 0 --parent <parent-id> --description "**SonarQube Key:** ...
**Rule:** ...
..."
```

For chore (everything else):
```bash
bd create --title "Reduce Cognitive Complexity (model.py)" --type chore --priority 2 --labels refactoring --parent <parent-id> --description "**SonarQube Key:** ...
**Rule:** ...
..."
```

**Create sequentially** - parallel `bd create` may conflict with SQLite. Do NOT dispatch parallel subagents for creation.

**Shell escaping:** If the SonarQube message contains special characters (`$`, backticks, `!`), use single quotes for the description or escape them. Prefer using `--body-file -` with stdin to avoid shell escaping issues for long descriptions.

**SonarCloud URL:** Hardcoded `https://sonarcloud.io` base.

### 7. Report

#### 7a. Main Branch Report

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

#### 7b. PR Report

```
Fixed in session: 3
Created subtasks: 2

Skipped (already in beads): 0
Skipped (user): 0
```

## Scope Boundaries

### This Skill DOES:
- Detect main vs PR mode
- List and select SonarQube projects
- Load issues via MCP tool (in subagent)
- Deduplicate against existing beads tasks
- Show preview table with classification
- Let user select which issues to import
- Create beads tasks with proper format
- Fix issues in-place (PR mode)
- Show summary report
- Paginate large result sets

### This Skill Does NOT:
- Auto-detect SonarQube project from repo
- Group similar issues
- Provide dry-run mode
- Filter by severity on input
- Update existing beads tasks from SonarQube
- Configure SonarCloud base URL
- Create branches or manage git workflow
- Run bd sync (separate concern; user runs after if needed)
- Auto-create without preview

## Red Flags - STOP

If you're thinking any of these, STOP and follow the workflow:

- "I'll create all tasks without showing preview"
- "User said sync, so I'll import everything"
- "I'll skip deduplication, it's probably fine"
- "Let me guess the project key from the repo"
- "I'll group similar issues to reduce noise"
- "I know the parent task, no need to confirm"
- "bd create in parallel is faster"
- "I'll add severity filtering to help"
- "Skip the subagent, I'll do it inline"
- "No need to show the table, just create"

**All of these mean: Follow the workflow. Preview first. User decides.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Sync means import everything" | Sync means preview + user selection. Never auto-create. |
| "Deduplication is overhead" | Without dedup, you create duplicate tasks. Always dedup. |
| "I know the right parent" | Ask. User might want a different parent or new one. |
| "Parallel bd create is faster" | SQLite conflicts. Sequential is correct. |
| "Subagent is overkill" | Subagent keeps context clean. 500+ issues pollute context. |
| "Grouping would be helpful" | Out of scope. Show flat list, let user decide. |
| "Skip table for small batches" | Always show table. Even 1 issue gets a preview. |
| "PR mode is just main mode" | PR mode has fix-now option. Different parent logic. Different actions. |
| "I'll auto-detect the project" | Out of scope. Ask or use argument. |

## Examples

### BAD: Auto-import without preview

```
User: "/flow:sonar-sync NoNameItem_statuskit"
Agent: [Fetches 47 issues from SonarQube]
       [Creates 12 beads tasks automatically]
       Done! Created 12 tasks.
```

**Problems:**
- No preview shown
- No user selection
- No deduplication check mentioned
- No parent task confirmation

### GOOD: Full main branch workflow

```
User: "/flow:sonar-sync NoNameItem_statuskit"
Agent: [Detects no PR - main branch mode]
       [Dispatches subagent to load and dedup issues]

       Found SonarQube task:
         [E] StatusKit Sonar Issues (claude-tools-4u3) | P2 · open

       Use as parent? (yes / other / new)

User: yes

Agent: New SonarQube issues (9):

       | #  | Severity | Type  | File                                | Line | Message                    |
       |----|----------|-------|-------------------------------------|------|----------------------------|
       | 1  | BLOCKER  | bug   | src/statuskit/setup/gitignore.py    | 62   | Path traversal from user.. |
       | 2  | HIGH     | chore | src/statuskit/modules/model.py      | 70   | Cognitive Complexity 18>15 |
       ...

       Already in beads: 3 | Skipped (not OPEN): 35

       What to create?
       - 'all' (or empty input) - create all 9
       - Numbers: 1,3,5
       - 'n' - skip

User: 1,2,3

Agent: [Creates 3 tasks sequentially]

       Created: 3
         - bug (P0): 1
         - chore (refactoring): 2

       Skipped (already in beads): 3
       Skipped (user): 6
```

**Correct because:**
- Detected mode
- Used subagent for loading
- Confirmed parent task
- Showed preview table
- Let user select
- Created sequentially
- Showed report

### GOOD: PR mode with fix and defer

```
User: "/flow:sonar-sync NoNameItem_statuskit --pr 42"
Agent: [PR mode: checking issues for PR #42]
       [Dispatches subagent]

       Current task: [F] Add git module (claude-tools-c7b) | in_progress

       Create subtasks under claude-tools-c7b? (yes / other)

User: yes

Agent: New SonarQube issues (3):

       | # | Severity | Type  | File              | Line | Message                    |
       |---|----------|-------|-------------------|------|----------------------------|
       | 1 | HIGH     | chore | modules/git.py    | 45   | Cognitive Complexity 20>15 |
       | 2 | MEDIUM   | chore | modules/git.py    | 102  | Duplicating literal 3x     |
       | 3 | LOW      | chore | modules/git.py    | 150  | Rename variable to match.. |

       What to do with these issues?
       - Numbers to fix now (e.g., 1,2)
       - Numbers to create subtasks (e.g., 3)
       - 'all fix' / 'all task' / 'n'

User: 1 fix, 2,3 task

Agent: [Reads modules/git.py:45, proposes fix, applies, commits]

       Fixed in session: 1
       Created subtasks: 2

       Skipped (already in beads): 0
       Skipped (user): 0
```

**Correct because:**
- Used PR mode
- Confirmed parent from session context
- Showed preview
- Mixed fix + defer actions
- Report covers both

### BAD: Skip deduplication

```
Agent: [Fetches issues]
       [Shows 15 issues in table]
       [User selects all]
       [Creates 15 tasks - but 5 already existed in beads!]
```

**Problem:** Skipped dedup step. Now 5 duplicate tasks exist.

### BAD: Parallel bd create

```
Agent: [User selected 8 issues]
       [Dispatches 8 parallel bd create calls]
       Error: database is locked
```

**Problem:** SQLite doesn't handle parallel writes. Create sequentially.

## Edge Cases

### No Open Issues

```
No new SonarQube issues to import.

Total: 47, open: 0, already in beads: 0.
All issues are resolved.
```

### All Issues Already in Beads

```
No new SonarQube issues to import.

Total: 47, open: 12, already in beads: 12.
All open issues are already tracked.
```

### Large Result Set (>100 new)

After creating first batch:
```
134 new issues remaining.

1. Load next 100
2. Stop

Your choice:
```

If user chooses 1, dispatch subagent again with offset.

### No SonarQube Projects Found

```
No SonarQube projects found.

Check that:
- SonarQube MCP server is connected
- You have access to at least one project
- Project key is correct (if provided as argument)
```

### PR Mode: No Current Task

```
No in_progress task found in session context.

Attempting to extract from branch name...
Branch: feature/claude-tools-c7b-git-module
Extracted task: claude-tools-c7b

Use claude-tools-c7b as parent? (yes / other)
```

If branch doesn't match pattern:
```
Could not determine parent task.

1. Specify task ID
2. Skip parent (create standalone tasks)

Your choice:
```

### Mixed Severity in Selection

User selects issues 1 (BLOCKER) and 3 (MEDIUM):
- Issue 1 -> bug, P0
- Issue 3 -> chore, P2, label: refactoring

Classification applies per-issue, not per-batch.

### MCP Tool Failure

If `mcp__sonarqube__search_sonar_issues_in_projects` fails (server not connected, auth error, etc.):
```
SonarQube request failed: <error message>

Check that:
- SonarQube MCP server is connected and configured
- Your authentication token is valid
- The project key "<key>" exists and you have access
```

Stop here. Do not retry automatically.

### Partial Creation Failure

If `bd create` fails mid-batch (e.g., after creating 3 of 7 tasks):
```
Error creating task 4/7: <error message>

Created so far: 3
  - bug (P0): 1
  - chore (refactoring): 2

Remaining: 4 tasks not created.

1. Retry remaining tasks
2. Stop (keep what was created)

Your choice:
```

Do not silently skip failed tasks.

### PR Mode: Fix Fails

If an attempted fix doesn't work (can't determine fix, tests break, etc.):
```
Could not fix issue #1: <reason>

1. Create subtask instead
2. Skip this issue

Your choice:
```

Never leave broken code from a failed fix attempt. Revert if needed.

## The Bottom Line

**Preview before creating. User selects what to import.**

Always show the table. Always let user choose. Always dedup first.
Sequential creation. Subagent for loading. Report at the end.

Never auto-import. Never skip dedup. Never guess the project.
