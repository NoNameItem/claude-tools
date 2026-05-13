# bd-tree Root Separator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Escape the dot after the root number in `bd-tree.py` output (`1.` → `1\.`) so Markdown renderers stop treating consecutive roots as one ordered list, restoring the blank-line separator between every pair of root tasks.

**Architecture:** Single one-line edit in `format_task_line` of `plugins/flow/skills/starting-task/scripts/bd-tree.py`, gated by `is_root`. Child numbers (`1.1`, `2.4`) are unaffected because their dot is internal to the number. Test coverage is added in `test_bd_tree.py`; one existing assertion is updated.

**Tech Stack:** Python 3.12+, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-05-13-bd-tree-root-separator-design.md`

**Beads task:** `claude-tools-elf.12`

---

### Task 1: Escape root dot and update tests

**Files:**
- Modify: `plugins/flow/skills/starting-task/scripts/bd-tree.py:211`
- Modify: `plugins/flow/skills/starting-task/scripts/test_bd_tree.py` (update one existing test, add two new tests)

- [ ] **Step 1: Add failing test for escaped root dot**

Open `plugins/flow/skills/starting-task/scripts/test_bd_tree.py`. Locate `class TestFormatTaskLine`, find the existing test `test_child_numbering_preserved` (around line 214). Add the following two tests immediately after it, inside the same class:

```python
    def test_root_number_dot_escaped(self):
        """Root number renders with backslash-escaped dot to disable Markdown list parsing."""
        task = make_task("test-1", issue_type="task", priority=2, status="open")
        line = format_task_line(task, prefix="", number="1", is_root=True, min_priority=None)
        assert "1\\." in line
        # The literal "1. " (digit, dot, space) must NOT appear at root level.
        assert "1. " not in line

    def test_child_number_dot_not_escaped(self):
        """Child numbers keep their dot unescaped; only roots are escaped."""
        task = make_task("test-1", issue_type="task", priority=2, status="open")
        line = format_task_line(task, prefix="├─ ", number="1.1", is_root=False, min_priority=None)
        assert "1.1 " in line
        assert "1\\." not in line
```

- [ ] **Step 2: Update the existing root-numbering integration test**

In the same file, locate `test_root_task_becomes_root_1` (around line 309). Replace the assertion `assert "1." in lines[0]` with `assert "1\\." in lines[0]`. The full updated test should read:

```python
    def test_root_task_becomes_root_1(self):
        """The selected root task's first line contains '1\\.' numbering."""
        tasks = self._parse(
            [
                issue("proj-aaa", title="Root A"),
                issue("proj-bbb", title="Root B"),
            ],
        )
        # Even though proj-bbb would be 2nd normally, with --root it becomes 1.
        # Bold wrapping may prepend **, so check for "1\." presence (escaped dot).
        lines = build_tree(tasks, root_id="proj-bbb")
        assert "1\\." in lines[0]
        assert "Root B" in lines[0]
```

- [ ] **Step 3: Run the new and updated tests to verify they fail**

Run: `cd /Users/artem.vasin/Coding/claude-tools && uv run pytest plugins/flow/skills/starting-task/scripts/test_bd_tree.py::TestFormatTaskLine::test_root_number_dot_escaped plugins/flow/skills/starting-task/scripts/test_bd_tree.py::TestFormatTaskLine::test_child_number_dot_not_escaped plugins/flow/skills/starting-task/scripts/test_bd_tree.py -k "test_root_task_becomes_root_1 or test_root_number_dot_escaped or test_child_number_dot_not_escaped" -v`

Expected:
- `test_root_number_dot_escaped` → FAIL (`"1\\." in line` is False because line still has `"1."`)
- `test_root_task_becomes_root_1` → FAIL (same reason)
- `test_child_number_dot_not_escaped` → PASS (children are already unescaped)

- [ ] **Step 4: Implement the one-line change in `format_task_line`**

Open `plugins/flow/skills/starting-task/scripts/bd-tree.py`. Locate `format_task_line` (line 196) and find this block (around lines 210-212):

```python
    # Root items get trailing dot: "1." Children don't: "1.1"
    num_display = f"{number}." if is_root else number
```

Replace it with:

```python
    # Root items get backslash-escaped dot ("1\.") to prevent Markdown
    # renderers from treating consecutive roots as a single ordered list,
    # which would collapse the blank separator line between them.
    # Children keep the dot unescaped because it's internal to nested numbers ("1.1").
    num_display = f"{number}\\." if is_root else number
```

(In Python source, `f"{number}\\."` produces the literal two-character suffix `\.` — a backslash followed by a dot.)

- [ ] **Step 5: Run the full bd-tree test suite to verify all tests pass**

Run: `cd /Users/artem.vasin/Coding/claude-tools && uv run pytest plugins/flow/skills/starting-task/scripts/test_bd_tree.py -v`

Expected: All tests PASS, including the two new ones and the updated `test_root_task_becomes_root_1`. No regressions.

If any tests besides the three above fail, inspect them — they may also assert on `"1."` at root level and need the same `"1\\."` update. Apply the same fix and re-run.

- [ ] **Step 6: Manual verification — run the script against real data**

Run: `cd /Users/artem.vasin/Coding/claude-tools && bd graph --all --json | python3 plugins/flow/skills/starting-task/scripts/bd-tree.py | head -40`

Expected: Lines for root tasks start with `1\.`, `2\.`, `3\.`, etc. (literal backslash visible in raw output). Sub-rows (`├─ 1.1`, `└─ 2.4`) are unchanged.

When this output is rendered in chat (Markdown), confirm a blank line appears before every root, not only the second.

Also verify subtree mode: `bd graph --all --json | python3 plugins/flow/skills/starting-task/scripts/bd-tree.py --root 5dl | head -10`

Expected: The selected subtree root starts with `1\.`; nested children unchanged.

- [ ] **Step 7: Lint and format**

Run: `cd /Users/artem.vasin/Coding/claude-tools && uv run ruff format plugins/flow/skills/starting-task/scripts/bd-tree.py plugins/flow/skills/starting-task/scripts/test_bd_tree.py && uv run ruff check --fix plugins/flow/skills/starting-task/scripts/bd-tree.py plugins/flow/skills/starting-task/scripts/test_bd_tree.py`

Expected: No changes needed, or only trivial whitespace fixups. No new lint errors.

- [ ] **Step 8: Commit**

```bash
cd /Users/artem.vasin/Coding/claude-tools
git add plugins/flow/skills/starting-task/scripts/bd-tree.py plugins/flow/skills/starting-task/scripts/test_bd_tree.py
git commit -m "$(cat <<'EOF'
fix(flow): escape root dot in bd-tree output for Markdown rendering (claude-tools-elf.12)

Root lines (1., 2., 3., …) match Markdown's ordered-list pattern, so
renderers collapse the blank separator between consecutive roots. Escape
the dot (1\.) only on root lines so list-mode is never entered and the
blank line emitted by build_tree renders as a paragraph break in every
case. Children (1.1, 2.4) are unchanged because their dot is internal.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds. Pre-commit hooks (`ruff-format`, `ruff`, single-package-commit, beads) all pass. If `ruff-format` or `ruff` reports issues, fix them, re-stage, and create a NEW commit (do not amend).
