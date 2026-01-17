# Flow:Start Task Display Improvement Design

## Overview

`/flow:start` now displays tasks as a hierarchical tree with rich metadata, replacing the flat list. This improves readability and navigation.

## Changes

### 1. Hierarchical Task Tree Instead of Flat List

**Current state:**
```
1. [● P1] [epic] claude-tools-5dl: StatusKit
2. [● P2] [feature] claude-tools-c7b: Git module
3. [● P2] [task] claude-tools-5dl.1: Distribution: PyPI package setup
```

**New state:**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution: PyPI package setup (claude-tools-5dl.1) | P2 · open | #statuskit
   ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

2. [F] External feature (claude-tools-xyz) | P2 · open
```

### 2. New Task Display Format

**Structure:**
```
[Type] Title (ID) | Priority · Status | #labels
```

**Components:**

- **Type** - single letter in brackets:
  - `[E]` = epic
  - `[F]` = feature
  - `[T]` = task
  - `[B]` = bug
  - `[C]` = chore

- **Title and ID** - task title with ID in parentheses

- **First metadata group** (separator `|`):
  - Priority (P0-P4)
  - Status (open, in_progress, blocked, deferred)
  - Separator between them: ` · `

- **Second metadata group** (separator `|`):
  - Labels with `#` prefix, space-separated
  - **If no labels** - section omitted entirely (remove trailing `|`)

**Examples:**
```
[F] Git module (claude-tools-c7b) | P2 · open | #statuskit #python
[T] Some task (claude-tools-xyz) | P3 · open
```

## Data Source and Tree Building

### Source

`bd graph --all --json` returns all task graphs with complete dependency information.

**Output structure:**
```json
[
  {
    "Root": {...},
    "Issues": [...],
    "Dependencies": [...],
    "IssueMap": {...}
  }
]
```

### Building the Tree

1. Parse JSON, get all Issues and Dependencies
2. Build parent-child relationships from Dependencies (type = "parent-child")
3. Identify root tasks: all tasks without parents
4. Recursively build tree from roots to children

### Filtering Rules

**Show:**
- Tasks with status `open` or `in_progress`

**Hide:**
- Tasks with status `closed`
- Blocked tasks (status `blocked` OR has unclosed blocking dependencies of type `blocks`)

**Special cases:**
- Tasks with status `deferred`: show only if they are parents of unblocked children
- Blocked tasks: show if they have unblocked descendants (unusual case, but better to keep context visible)

### Sorting on Each Level

1. By status: `in_progress` → `open` → `blocked` → `deferred`
2. By priority: P0 → P1 → P2 → P3 → P4

## Tree Visualization

### ASCII Tree Structure

- `├─` for intermediate children
- `└─` for last child
- Indentation for nesting

### Numbering

- **Root tasks** (no parents): `1.` `2.` `3.`
- **First level children**: `1.1` `1.2` `1.3`
- **Second level children**: `1.1.1` `1.1.2`
- And so on by hierarchy

### Examples

**Simple tree:**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution: PyPI package (claude-tools-5dl.1) | P2 · open | #statuskit
   ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

2. [F] External feature (claude-tools-xyz) | P2 · open
```

**Deep nesting:**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   │      ├─ 1.1.1 [T] Subtask 1 (claude-tools-c7b.1) | P2 · open
   │      └─ 1.1.2 [T] Subtask 2 (claude-tools-c7b.2) | P3 · open
   └─ 1.2 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
```

**Mixed structure:**
```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
   └─ 1.2 [T] CI/CD (claude-tools-5dl.2) | P2 · open | #statuskit

2. [F] Standalone feature A (claude-tools-abc) | P2 · open

3. [F] Standalone feature B (claude-tools-def) | P3 · open | #experimental
```

## User Interaction

### Task Selection

User selects a task by:

1. **By number from tree:**
   - `1` - select root task
   - `1.2` - select child task
   - `1.1.2` - select third level task

2. **By task ID:**
   - `claude-tools-c7b` - direct selection by ID

3. **By search (if called with argument):**
   - `/flow:start git` - show tree with filtered results

4. **Create new task:**
   - `new` or `create` - launches `bd create` to create new task

**Example dialog:**

```
Assistant: Доступные задачи:

1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open | #statuskit
   ├─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open | #statuskit
   └─ 1.3 [F] Beads module (claude-tools-5d1) | P2 · open | #statuskit

2. [F] External feature (claude-tools-xyz) | P2 · open

Выберите задачу (по номеру или ID), или введите 'new' для создания новой:

User: 1.2
```

### Selected Task Display

Show detailed information before taking action (consultation over assumption).

**Format:**

```
┌─ [Type] Title ────────────────────────────────────────────┐
│ ID: <task-id>                                             │
│ Priority: <priority>  Status: <status>  Type: <type>      │
│ Labels: #label1 #label2                                   │
├───────────────────────────────────────────────────────────┤
│ DESCRIPTION                                               │
│ <full task description>                                   │
│                                                            │
├───────────────────────────────────────────────────────────┤
│ LINKS                                                      │
│ Design: docs/plans/...                                    │
│ Plan: docs/plans/...                                      │
│                                                            │
├───────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                              │
│ Depends on:                                               │
│   → claude-tools-xxx: Some task (closed)                  │
│                                                            │
│ Blocks:                                                   │
│   → claude-tools-yyy: Another task (open)                 │
└───────────────────────────────────────────────────────────┘
```

**Sections:**
- **Metadata** - always
- **Description** - if present
- **Links** - if description contains `Design: ...` or `Plan: ...` lines
- **Dependencies** - if present

**Example:**

```
┌─ [F] Git module ──────────────────────────────────────────┐
│ ID: claude-tools-c7b                                      │
│ Priority: P2  Status: open  Type: feature                 │
│ Labels: #statuskit #python                                │
├───────────────────────────────────────────────────────────┤
│ DESCRIPTION                                               │
│ Модуль отображения git-статуса:                          │
│ - Текущая директория (имя проекта)                       │
│ - Ветка и её статус                                       │
│ - Количество изменений (staged/unstaged)                  │
│ - Хеш и возраст последнего коммита                        │
├───────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                              │
│ Depends on:                                               │
│   → claude-tools-5dl: StatusKit (in_progress)             │
└───────────────────────────────────────────────────────────┘
```

## Edge Cases

### Case 1: No Available Tasks

When filtering leaves no tasks:

```
Нет доступных задач для работы.

Причины:
- Все задачи закрыты
- Все открытые задачи заблокированы
- Все задачи отложены (deferred)

Что вы хотите сделать?
1. bd blocked - посмотреть заблокированные задачи
2. bd list --status=deferred - посмотреть отложенные
3. new - создать новую задачу

Ваш выбор:
```

### Case 2: Search Found Nothing

When search finds no matches:

```
Поиск "git" не нашел задач.

Доступные задачи:
[show full tree without filter]

Выберите задачу (по номеру или ID), или введите 'new' для создания новой:
```

### Case 3: Multiple Graphs

When `bd graph --all --json` returns multiple graphs:

```
1. [E] StatusKit (claude-tools-5dl) | P1 · in_progress | #statuskit
   ├─ 1.1 [T] Distribution (claude-tools-5dl.1) | P2 · open
   └─ 1.2 [F] Git module (claude-tools-c7b) | P2 · open

2. [E] Another Project (other-project-abc) | P2 · open | #other
   └─ 2.1 [F] Feature X (other-project-abc.1) | P2 · open

3. [F] Standalone task (standalone-xyz) | P3 · open
```

Merge all graphs into one tree with sequential root numbering.

### Case 4: Task Already in_progress

When selected task has `in_progress` status:

```
┌─ [F] Git module ──────────────────────────────────────────┐
│ ⚠️  Задача уже в работе (in_progress)                     │
│                                                            │
│ ID: claude-tools-c7b                                      │
│ Priority: P2  Status: in_progress  Type: feature          │
...
```

Continue normal workflow (branch check, questions), but don't update status.

## Implementation Details

### Tree Building Algorithm

1. **Get data:**
   ```bash
   bd graph --all --json
   ```
   Parse JSON, get array of graphs with Issues and Dependencies

2. **Build parent-child map:**
   - Create dictionary `parent_to_children: {parent_id: [child_ids]}`
   - Iterate Dependencies where `type == "parent-child"`
   - `dependency.issue_id` is child, `dependency.depends_on_id` is parent

3. **Determine task blocking:**
   - Task is blocked if:
     - `status == "blocked"` OR
     - Exists dependency of type `blocks` where `depends_on_id` points to unclosed task

4. **Filter tasks:**
   ```python
   def should_show_task(task, children):
       # Closed - never
       if task.status == "closed":
           return False

       # Open and in_progress - always
       if task.status in ["open", "in_progress"]:
           return True

       # Deferred and blocked - only if has unblocked children
       if task.status in ["deferred", "blocked"]:
           return has_unblocked_children(task, children)

       return False
   ```

5. **Build hierarchy with numbering:**
   ```python
   def build_tree(root_tasks, parent_to_children, number_prefix=""):
       result = []
       for idx, task in enumerate(root_tasks, 1):
           number = f"{number_prefix}{idx}" if number_prefix else str(idx)
           result.append((number, task))

           if task.id in parent_to_children:
               children = parent_to_children[task.id]
               child_tree = build_tree(children, parent_to_children, f"{number}.")
               result.extend(child_tree)

       return result
   ```

6. **Sort on each level:**
   ```python
   status_order = {"in_progress": 0, "open": 1, "blocked": 2, "deferred": 3}

   tasks.sort(key=lambda t: (
       status_order.get(t.status, 99),
       t.priority
   ))
   ```

7. **Map numbers to task_id:**
   - Create dictionary `number_to_id: {"1": "claude-tools-5dl", "1.2": "claude-tools-c7b"}`
   - Use when parsing user choice

### Parse User Choice

```python
def parse_user_choice(input, number_to_id):
    input = input.strip()

    # Check for "new" or "create"
    if input.lower() in ["new", "create"]:
        return ("new", None)

    # Check for number from tree
    if input in number_to_id:
        return ("select", number_to_id[input])

    # Check for direct ID
    if input.startswith("claude-tools-") or similar_pattern:
        return ("select", input)

    return ("unknown", None)
```

## Migration Path

1. Update `/flow:start` skill to use new tree display logic
2. Keep existing workflow after task selection (branch check, consultation, etc.)
3. No breaking changes - all existing behavior preserved, only display improved
