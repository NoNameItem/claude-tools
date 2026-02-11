# Task Card Script Design

**Task:** claude-tools-xhz
**Date:** 2026-02-10

## Problem

The starting-task and continue-issue skills display task details in a Unicode box-drawing frame. The LLM generates this
frame manually, and it consistently breaks: the right edge misaligns because the LLM cannot accurately calculate
character widths for Unicode content (Cyrillic, emoji, mixed-width characters).

## Solution

A Python script (`bd-card.py`) that takes `bd show <id> --json` via stdin and outputs a properly aligned Unicode card.
The script calculates exact character widths using `unicodedata.east_asian_width()`, guaranteeing correct alignment.

## Script Specification

### Location

`plugins/flow/skills/starting-task/scripts/bd-card.py` (alongside `bd-tree.py`)

### Invocation

```bash
bd show <task-id> --json | python3 <skill-base-dir>/scripts/bd-card.py
```

### Input

JSON array from `bd show --json` (stdin). Uses first element of the array.

Fields used:

- `id`, `title`, `issue_type` — title section
- `priority`, `status`, `labels` — metadata and labels
- `description` — description section, also parsed for `Design:` / `Plan:` / `Git:` links
- `dependencies` — dependencies section, each with `dependency_type`

### Output

Unicode box-drawn card printed to stdout (plain text, no markdown markers). The skill wraps the output in a ``` code
block for monospace rendering. **Critical:** every line must have the same visual width.

Example (full card):

```
┌─ Task ─────────────────────────────────────────────────────────────────────┐
│ Улучшить отображение текущей задачи в flow:starting-task                   │
│                                                                            │
│ #flow                                                                      │
├────────────────────────────────────────────────────────────────────────────┤
│ ID: claude-tools-xhz                                                       │
│ Priority: P4  Status: in_progress  Type: task                              │
├────────────────────────────────────────────────────────────────────────────┤
│ DESCRIPTION                                                                │
│ Сейчас текущая задача выводится в рамке, которая выглядит непонятно.       │
│ Нужно продумать более удачный формат отображения.                          │
│                                                                            │
│ TODO:                                                                      │
│ - Проанализировать текущий вывод                                           │
│ - Продумать альтернативные варианты отображения                            │
│ - Реализовать выбранный вариант                                            │
├────────────────────────────────────────────────────────────────────────────┤
│ LINKS                                                                      │
│ Design: docs/plans/2026-02-10-task-card-script-design.md                   │
├────────────────────────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                                               │
│ Parent:                                                                    │
│   → claude-tools-elf: Flow Improvements (open)                             │
└────────────────────────────────────────────────────────────────────────────┘
```

Example (minimal card — no labels, no description, no links, no dependencies):

```
┌─ Feature ──────────────────────────────────────────────────────────────────┐
│ Add dark mode support                                                      │
├────────────────────────────────────────────────────────────────────────────┤
│ ID: claude-tools-abc                                                       │
│ Priority: P2  Status: open  Type: feature                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Card Layout Rules

1. **Width**: fixed at 80 characters. Content area is 76 characters (80 minus `│ ` prefix and ` │` suffix).
2. **Word wrap**: long lines in description and labels wrap at word boundaries to fit within the card.
3. **Bullet list wrap**: lines starting with `- ` wrap with indent aligned to the text after the marker:
   ```
   │ - Very long bullet item that does not fit on a single              │
   │   line continues with indent under the text                        │
   ```
4. **Dependency line wrap**: long dependency lines wrap with indent aligned to the text after `→ `:
   ```
   │   → claude-tools-lmr: flow:start does not suggest                  │
   │     selecting a subtask when open children exist (open)             │
   ```
5. **Character width**: use `unicodedata.east_asian_width()` from stdlib. Characters with width `W` or `F` occupy 2
   terminal cells, all others occupy 1. No external dependencies. Emoji width glitches are accepted as rare.
6. **Type word**: Epic, Feature, Bug, Task, Chore (in the top border).

### Sections

Sections are rendered in order. Title and Metadata are always present; others are conditional:

| Section      | Condition                                          | Content                                                                   |
|--------------|----------------------------------------------------|---------------------------------------------------------------------------|
| Title        | Always                                             | Task title (word-wrapped). Type word in top border.                       |
| Labels       | If `labels` is non-empty                           | Labels prefixed with `#`, separated by spaces. Blank line before labels.  |
| Metadata     | Always                                             | ID, Priority, Status, Type (on separate lines)                            |
| Description  | If `description` is non-empty (after link removal) | Full description text with `Design:`/`Plan:`/`Git:` lines removed         |
| Links        | If description contains `Design:` or `Plan:` lines | Extracted `Design:` and `Plan:` lines (not `Git:`)                        |
| Dependencies | If `dependencies` array is non-empty               | Grouped by dependency type                                                |

### Link Parsing

Lines matching `Design:`, `Plan:`, or `Git:` are extracted from the description:

- `Design:` and `Plan:` lines are moved to the LINKS section
- `Git:` lines are removed from description but **not** shown in LINKS
- Multiple `Design:` or `Plan:` lines are all shown
- Matching is case-sensitive (must start with exact `Design:`, `Plan:`, or `Git:`)

### Dependency Grouping

Dependencies from the JSON `dependencies` array are grouped by `dependency_type`:

| `dependency_type` | Display header |
|-------------------|----------------|
| `parent-child`    | `Parent:`      |
| `dependency`      | `Depends on:`  |

For reverse dependencies (tasks this one blocks), if present:

| Reverse type  | Display header |
|---------------|----------------|
| blocked tasks | `Blocks:`      |

Each dependency line: `  → <id>: <title> (<status>)`

### No "Already In Progress" Warning

The previous design showed `⚠️ Задача уже в работе (in_progress)` for tasks with `in_progress` status. This is removed —
the status field in metadata is sufficient.

## Skill Changes

### starting-task/skill.md

**Step 3 (Show Task Description):**

- Remove the manual box template
- Replace with: run `bd show <id> --json | python3 <skill-base-dir>/scripts/bd-card.py`
- Output the script result as-is (in a code block to preserve alignment)
- Remove `⚠️ Задача уже в работе` instruction

**End of skill (after steps 7-8):**

- LLM writes a text summary about the branch and status
- Then runs the same script to show the card
- Format:
  ```
  Начинаем работу. Ветка: `feature/claude-tools-xhz-...`

  [card output from bd-card.py]
  ```

**Examples section:**

- Update examples to show script invocation instead of manual frames

### continue-issue/skill.md

**Step 8 (Show Task Card):**

- Remove manual box template
- Replace with: run `bd show <id> --json | python3 <skill-base-dir>/scripts/bd-card.py`
- Output in a code block

**Examples section:**

- Update examples to use script output

## Dependencies

None. Uses only Python stdlib (`json`, `sys`, `textwrap`, `unicodedata`).

## Out of Scope

- No CLI arguments for the script (all data comes from stdin JSON)
- No color output (terminal compatibility varies)
- No interactive features
