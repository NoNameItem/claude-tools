# bd-tree.py: Stable Blank-Line Separator Between Root Tasks

**Task:** claude-tools-elf.12
**Date:** 2026-05-13
**Status:** Design

## Problem

The task tree shown by `/flow:start` (and other skills that consume `plugins/flow/skills/starting-task/scripts/bd-tree.py`) is meant to display a blank line between each root task (epic or top-level item) for visual separation.

The script already emits a blank line between consecutive root trees (see `build_tree`, lines 349-350: `lines.append("")`). The raw output, inspected with `cat -e`, contains a `$$` (empty line) between every pair of roots.

However, when this output is rendered as Markdown in the Claude Code UI, the blank line only appears **between the first two roots** — between the first epic and the second. For all subsequent roots, the blank line is collapsed by the Markdown renderer.

### Root cause

Root lines begin with `1.`, `2.`, `3.`, … — the exact pattern Markdown uses for ordered-list items. The renderer treats the consecutive root lines as a single ordered list and collapses single blank lines between list items.

The blank line between roots 1 and 2 survives only because root 1 has a nested subtree (lines starting with `├─`/`└─`). Those lines break the renderer out of list-mode, so the following blank line becomes a paragraph break. When two roots are simple lines (e.g. an epic with no visible children, or a leaf task), the renderer stays in list-mode and the blank line is collapsed.

## Solution

Escape the dot after the root number: render `1\.` instead of `1.` in `format_task_line` when `is_root=True`. The backslash disables Markdown's ordered-list pattern matching for that line, so consecutive roots are no longer treated as one list, and blank lines between them render as proper paragraph breaks in every case.

Child numbers (`1.1`, `2.4`, `1.4.1`) are not affected — the dot is in the middle of the number, not at the end, so the list pattern does not match. They continue to render unchanged.

### Code change

`plugins/flow/skills/starting-task/scripts/bd-tree.py`, function `format_task_line`:

```python
# Root items get escaped dot to prevent Markdown list interpretation: "1\."
# Children keep dot as part of nested numbering: "1.1"
num_display = f"{number}\\." if is_root else number
```

This replaces the existing line:

```python
num_display = f"{number}." if is_root else number
```

No other code changes are required. The blank-line emission in `build_tree` (lines 349-350) already does the right thing at the text level; we only need to make the rendered output respect it.

## Testing

`plugins/flow/skills/starting-task/scripts/test_bd_tree.py` contains tests for `format_task_line`. Update and add:

- **Update existing root-line assertions** that check for `"1 "` / `"1. "` style patterns to use the new escaped form. The current assertions in `TestFormatTaskLine` check for substrings like `"❌ [B]"` or `"📋 [T]"` rather than the dot, so most pass unchanged — verify each.
- **Add `test_root_number_dot_escaped`:** assert that when `is_root=True`, the output contains `1\.` (not `1.` followed by a space).
- **Add `test_child_number_dot_not_escaped`:** assert that when `is_root=False` and `number="1.1"`, the output contains `1.1 ` (no backslash).
- **Existing `test_child_numbering_preserved`** (line 214) already checks `"├─ 1.1 📋 [T]"` — verify it still passes.

Manual verification:

1. Run `bd graph --all --json | python3 plugins/flow/skills/starting-task/scripts/bd-tree.py` and confirm the rendered tree in chat has a blank line before every root (not only the second).
2. Run with `--root <id>` and `--collapse` and `-s <term>` to confirm no regressions.

## Out of scope

- No change to child-line formatting.
- No change to blank-line emission logic in `build_tree`.
- No new visual separators (no horizontal rules, no `&nbsp;`).
- No change to the `bd-card.py` or other scripts.

## Files affected

- `plugins/flow/skills/starting-task/scripts/bd-tree.py` — one line edited in `format_task_line`.
- `plugins/flow/skills/starting-task/scripts/test_bd_tree.py` — add two tests, possibly tweak one assertion.
