# Task Card Script Design

**Task:** claude-tools-xhz
**Date:** 2026-02-10

## Problem

The starting-task and continue-issue skills display task details in a Unicode box-drawing frame. The LLM generates this
frame manually, and it consistently breaks: the right edge misaligns because the LLM cannot accurately calculate
character widths for Unicode content (Cyrillic, emoji, mixed-width characters).

## Solution

A Python script (`bd-card.py`) that takes `bd show <id> --json` via stdin and outputs a properly aligned Unicode card.
The script calculates exact character widths using `wcswidth`, guaranteeing correct alignment.

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

- `id`, `title`, `issue_type` — header
- `priority`, `status`, `labels` — metadata
- `description` — description section, also parsed for `Design:` / `Plan:` links
- `dependencies` — dependencies section, each with `dependency_type`

### Output

Unicode box-drawn card printed to stdout (plain text, no markdown markers). The skill wraps the output in a ``` code
block for monospace rendering. **Critical:** every line must have the same character count — the skill validates this.
Example:

```
┌─ [T] Task title here ──────────────────────────────────────┐
│ ID: claude-tools-xhz                                       │
│ Priority: P4  Status: in_progress  Type: task              │
│ Labels: #flow                                              │
├────────────────────────────────────────────────────────────┤
│ DESCRIPTION                                                │
│ Task description text that wraps properly at word          │
│ boundaries when it exceeds the card width.                 │
├────────────────────────────────────────────────────────────┤
│ LINKS                                                      │
│ Design: docs/plans/2026-01-20-design.md                    │
│ Plan: docs/plans/2026-01-20-plan.md                        │
├────────────────────────────────────────────────────────────┤
│ DEPENDENCIES                                               │
│ Parent:                                                    │
│   → claude-tools-elf: Flow Improvements (open)             │
│ Blocks:                                                    │
│   → claude-tools-abc: Some task (open)                     │
└────────────────────────────────────────────────────────────┘
```

### Card Layout Rules

1. **Width**: determined by the longest content line + 4 (for `│ ` prefix and ` │` suffix). Minimum 60, maximum 80
   characters.
2. **Word wrap**: long lines in description wrap at word boundaries to fit within the card.
3. **Character width**: use `unicodedata.east_asian_width()` from stdlib. Characters with width `W` or `F` occupy 2
   terminal cells, all others occupy 1. No external dependencies.
4. **Type letter**: E (epic), F (feature), B (bug), T (task), C (chore).

### Sections

All sections are rendered conditionally (except header and metadata which are always present):

| Section      | Condition                                          | Content                                                             |
|--------------|----------------------------------------------------|---------------------------------------------------------------------|
| Header       | Always                                             | `[TypeLetter] Title` in top border                                  |
| Metadata     | Always                                             | ID, Priority, Status, Type, Labels                                  |
| Description  | If `description` is non-empty                      | Full description text (with `Design:`/`Plan:`/`Git:` lines removed) |
| Links        | If description contains `Design:` or `Plan:` lines | Extracted link lines                                                |
| Dependencies | If `dependencies` array is non-empty               | Grouped by dependency type                                          |

### Dependency Grouping

Dependencies from the JSON `dependencies` array are grouped by `dependency_type`:

| `dependency_type` | Display header |
|-------------------|----------------|
| `parent-child`    | `Parent:`      |
| `dependency`      | `Depends on:`  |

For reverse dependencies (tasks this one blocks), if present:
| Reverse type | Display header |
|---|---|
| blocked tasks | `Blocks:` |

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
