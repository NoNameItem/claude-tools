# Commit Age Format Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix commit_age_format to decompose time into d/h/m units instead of just shortening labels.

**Architecture:** Replace `_format_commit_age` with three helper methods: `_parse_git_age` (parse git string to minutes), `_decompose_minutes` (break into d/h/m), and updated `_format_commit_age` (format based on config). Three formats: raw (git output), relative (decomposed + full names), compact (decomposed + short names).

**Tech Stack:** Python, pytest, termcolor

---

## Task 1: Add Helper Method `_parse_git_age`

**Files:**
- Modify: `packages/statuskit/src/statuskit/modules/git.py:192` (before `_format_commit_age`)
- Test: `packages/statuskit/tests/test_git_module.py`

**Step 1: Write failing tests for `_parse_git_age`**

Add to `test_git_module.py` after line 277 (after existing `test_format_commit_age_compact`):

```python
    def test_parse_git_age_seconds(self, make_render_context):
        """_parse_git_age returns 0 for seconds."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("30 seconds ago") == 0
        assert mod._parse_git_age("1 second ago") == 0

    def test_parse_git_age_minutes(self, make_render_context):
        """_parse_git_age converts minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("5 minutes ago") == 5
        assert mod._parse_git_age("1 minute ago") == 1
        assert mod._parse_git_age("69 minutes ago") == 69

    def test_parse_git_age_hours(self, make_render_context):
        """_parse_git_age converts hours to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 hours ago") == 120
        assert mod._parse_git_age("1 hour ago") == 60

    def test_parse_git_age_days(self, make_render_context):
        """_parse_git_age converts days to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("3 days ago") == 4320  # 3 * 1440
        assert mod._parse_git_age("1 day ago") == 1440

    def test_parse_git_age_weeks(self, make_render_context):
        """_parse_git_age converts weeks to minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 weeks ago") == 20160  # 2 * 7 * 1440

    def test_parse_git_age_months(self, make_render_context):
        """_parse_git_age converts months to minutes (30 days)."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("2 months ago") == 86400  # 2 * 30 * 1440

    def test_parse_git_age_years(self, make_render_context):
        """_parse_git_age converts years to minutes (365 days)."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("1 year ago") == 525600  # 365 * 1440

    def test_parse_git_age_invalid(self, make_render_context):
        """_parse_git_age returns None for invalid input."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._parse_git_age("invalid") is None
        assert mod._parse_git_age("") is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py::TestGitModule::test_parse_git_age_seconds -v`
Expected: FAIL with "AttributeError: 'GitModule' object has no attribute '_parse_git_age'"

**Step 3: Add constants and implement `_parse_git_age`**

Add constants after line 12 in `git.py`:

```python
# Time conversion constants
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 1440  # 24 * 60
_MINUTES_PER_WEEK = 10080  # 7 * 1440
_MINUTES_PER_MONTH = 43200  # 30 * 1440
_MINUTES_PER_YEAR = 525600  # 365 * 1440

# Git age unit to minutes mapping
_UNIT_TO_MINUTES: dict[str, int] = {
    "second": 0,
    "seconds": 0,
    "minute": 1,
    "minutes": 1,
    "hour": _MINUTES_PER_HOUR,
    "hours": _MINUTES_PER_HOUR,
    "day": _MINUTES_PER_DAY,
    "days": _MINUTES_PER_DAY,
    "week": _MINUTES_PER_WEEK,
    "weeks": _MINUTES_PER_WEEK,
    "month": _MINUTES_PER_MONTH,
    "months": _MINUTES_PER_MONTH,
    "year": _MINUTES_PER_YEAR,
    "years": _MINUTES_PER_YEAR,
}
```

Add method before `_format_commit_age` (around line 192):

```python
    def _parse_git_age(self, age_str: str) -> int | None:
        """Parse git relative age string to total minutes.

        Args:
            age_str: Relative age string from git (e.g., "2 hours ago")

        Returns:
            Total minutes, or None if parsing fails
        """
        parts = age_str.split()
        if len(parts) < _EXPECTED_COUNT_PARTS:
            return None

        try:
            num = int(parts[0])
        except ValueError:
            return None

        unit = parts[1]
        if unit not in _UNIT_TO_MINUTES:
            return None

        return num * _UNIT_TO_MINUTES[unit]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py -k "parse_git_age" -v`
Expected: All 8 tests PASS

**Step 5: Format and lint**

Run: `uv run ruff format packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py && uv run ruff check --fix packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py`

**Step 6: Type check**

Run: `uv run ty check`
Expected: No errors

**Step 7: Commit**

```bash
git add packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py
git commit -m "$(cat <<'EOF'
feat(statuskit): add _parse_git_age helper method

Parses git relative time strings ("2 hours ago") into total minutes.
Handles seconds, minutes, hours, days, weeks, months, years.

Part of claude-tools-5dl.7

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add Helper Method `_decompose_minutes`

**Files:**
- Modify: `packages/statuskit/src/statuskit/modules/git.py` (after `_parse_git_age`)
- Test: `packages/statuskit/tests/test_git_module.py`

**Step 1: Write failing tests for `_decompose_minutes`**

Add after `test_parse_git_age_invalid`:

```python
    def test_decompose_minutes_only_minutes(self, make_render_context):
        """_decompose_minutes returns only minutes for small values."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(5) == (0, 0, 5)
        assert mod._decompose_minutes(59) == (0, 0, 59)

    def test_decompose_minutes_hours_and_minutes(self, make_render_context):
        """_decompose_minutes breaks into hours and minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(69) == (0, 1, 9)
        assert mod._decompose_minutes(120) == (0, 2, 0)
        assert mod._decompose_minutes(150) == (0, 2, 30)

    def test_decompose_minutes_days_hours_minutes(self, make_render_context):
        """_decompose_minutes breaks into days, hours, minutes."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(1501) == (1, 1, 1)  # 1d 1h 1m
        assert mod._decompose_minutes(1560) == (1, 2, 0)  # 26h = 1d 2h
        assert mod._decompose_minutes(4320) == (3, 0, 0)  # 3 days

    def test_decompose_minutes_zero(self, make_render_context):
        """_decompose_minutes returns zeros for zero input."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})

        assert mod._decompose_minutes(0) == (0, 0, 0)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py::TestGitModule::test_decompose_minutes_only_minutes -v`
Expected: FAIL with "AttributeError: 'GitModule' object has no attribute '_decompose_minutes'"

**Step 3: Implement `_decompose_minutes`**

Add after `_parse_git_age`:

```python
    def _decompose_minutes(self, total_minutes: int) -> tuple[int, int, int]:
        """Decompose total minutes into days, hours, minutes.

        Args:
            total_minutes: Total number of minutes

        Returns:
            Tuple of (days, hours, minutes)
        """
        days = total_minutes // _MINUTES_PER_DAY
        remaining = total_minutes % _MINUTES_PER_DAY
        hours = remaining // _MINUTES_PER_HOUR
        minutes = remaining % _MINUTES_PER_HOUR
        return (days, hours, minutes)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py -k "decompose_minutes" -v`
Expected: All 4 tests PASS

**Step 5: Format and lint**

Run: `uv run ruff format packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py && uv run ruff check --fix packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py`

**Step 6: Type check**

Run: `uv run ty check`
Expected: No errors

**Step 7: Commit**

```bash
git add packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py
git commit -m "$(cat <<'EOF'
feat(statuskit): add _decompose_minutes helper method

Breaks total minutes into (days, hours, minutes) tuple.
Uses constants: 1 day = 1440 min, 1 hour = 60 min.

Part of claude-tools-5dl.7

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update `_format_commit_age` with New Logic

**Files:**
- Modify: `packages/statuskit/src/statuskit/modules/git.py` (replace `_format_commit_age`)
- Test: `packages/statuskit/tests/test_git_module.py` (update existing tests, add new)

**Step 1: Write failing tests for new behavior**

Replace existing `test_format_commit_age_relative` and `test_format_commit_age_compact` (lines 256-277) and add new tests:

```python
    def test_format_commit_age_raw(self, make_render_context):
        """_format_commit_age returns git output as-is for raw format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "raw"})

        assert mod._format_commit_age("2 hours ago") == "2 hours ago"
        assert mod._format_commit_age("69 minutes ago") == "69 minutes ago"

    def test_format_commit_age_relative_decomposed(self, make_render_context):
        """_format_commit_age decomposes and uses full names for relative format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "relative"})

        assert mod._format_commit_age("5 minutes ago") == "5 minutes ago"
        assert mod._format_commit_age("69 minutes ago") == "1 hour 9 minutes ago"
        assert mod._format_commit_age("120 minutes ago") == "2 hours ago"
        assert mod._format_commit_age("26 hours ago") == "1 day 2 hours ago"
        assert mod._format_commit_age("3 days ago") == "3 days ago"

    def test_format_commit_age_relative_singular(self, make_render_context):
        """_format_commit_age uses singular forms correctly."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "relative"})

        assert mod._format_commit_age("60 minutes ago") == "1 hour ago"
        assert mod._format_commit_age("1 day ago") == "1 day ago"

    def test_format_commit_age_compact_decomposed(self, make_render_context):
        """_format_commit_age decomposes and uses short names for compact format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod._format_commit_age("5 minutes ago") == "5m"
        assert mod._format_commit_age("69 minutes ago") == "1h 9m"
        assert mod._format_commit_age("120 minutes ago") == "2h"
        assert mod._format_commit_age("26 hours ago") == "1d 2h"
        assert mod._format_commit_age("3 days ago") == "3d"
        assert mod._format_commit_age("1501 minutes ago") == "1d 1h 1m"

    def test_format_commit_age_just_now(self, make_render_context):
        """_format_commit_age returns 'just now' for < 1 minute."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)

        mod_relative = GitModule(ctx, {"commit_age_format": "relative"})
        mod_compact = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod_relative._format_commit_age("30 seconds ago") == "just now"
        assert mod_compact._format_commit_age("30 seconds ago") == "just now"

    def test_format_commit_age_default_is_relative(self, make_render_context):
        """_format_commit_age defaults to relative format."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {})  # No format specified

        assert mod._format_commit_age("69 minutes ago") == "1 hour 9 minutes ago"

    def test_format_commit_age_invalid_fallback(self, make_render_context):
        """_format_commit_age returns input as-is for invalid strings."""
        data = make_input_data(model=make_model_data())
        ctx = make_render_context(data)
        mod = GitModule(ctx, {"commit_age_format": "compact"})

        assert mod._format_commit_age("invalid") == "invalid"
        assert mod._format_commit_age("") == ""
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py -k "format_commit_age" -v`
Expected: Most tests FAIL (new behavior not implemented)

**Step 3: Replace `_format_commit_age` implementation**

Replace the entire `_format_commit_age` method:

```python
    def _format_commit_age(self, age_str: str) -> str:
        """Format commit age according to config.

        Args:
            age_str: Relative age string from git (e.g., "2 hours ago")

        Returns:
            Formatted age string
        """
        # Raw format: return as-is
        if self.commit_age_format == "raw":
            return age_str

        # Parse git output to minutes
        total_minutes = self._parse_git_age(age_str)
        if total_minutes is None:
            return age_str  # Fallback for invalid input

        # Less than 1 minute
        if total_minutes == 0:
            return "just now"

        # Decompose into d/h/m
        days, hours, minutes = self._decompose_minutes(total_minutes)

        # Format based on config
        if self.commit_age_format == "compact":
            return self._format_compact(days, hours, minutes)
        else:
            # relative (default)
            return self._format_relative(days, hours, minutes)

    def _format_compact(self, days: int, hours: int, minutes: int) -> str:
        """Format time as compact string (e.g., '1d 2h 30m')."""
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "just now"

    def _format_relative(self, days: int, hours: int, minutes: int) -> str:
        """Format time as relative string (e.g., '1 day 2 hours ago')."""
        parts = []
        if days > 0:
            parts.append(f"{days} day" if days == 1 else f"{days} days")
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        return " ".join(parts) + " ago" if parts else "just now"
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py -k "format_commit_age" -v`
Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest packages/statuskit/tests/test_git_module.py -v`
Expected: All tests PASS

**Step 6: Format and lint**

Run: `uv run ruff format packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py && uv run ruff check --fix packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py`

**Step 7: Type check**

Run: `uv run ty check`
Expected: No errors

**Step 8: Commit**

```bash
git add packages/statuskit/src/statuskit/modules/git.py packages/statuskit/tests/test_git_module.py
git commit -m "$(cat <<'EOF'
fix(statuskit): decompose commit age into d/h/m units

BREAKING: Default format 'relative' now decomposes time.
- 69 minutes ago -> 1 hour 9 minutes ago
- Old behavior available via commit_age_format = "raw"

Three formats:
- raw: original git output
- relative: decomposed + full names + "ago" (default)
- compact: decomposed + short names (1h 9m)

Fixes claude-tools-5dl.7

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Manual Testing

**Step 1: Test with real git repo**

```bash
cd /Users/artem.vasin/Coding/claude-tools/.worktrees/fix-claude-tools-5dl.7-compact-age-format

# Test compact format
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"'$(pwd)'","project_dir":"'$(pwd)'"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | STATUSKIT_CONFIG='{"modules":["git"],"git":{"commit_age_format":"compact"}}' uv run statuskit

# Test relative format (default)
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"'$(pwd)'","project_dir":"'$(pwd)'"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | uv run statuskit

# Test raw format
echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"'$(pwd)'","project_dir":"'$(pwd)'"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":1000}}}' | STATUSKIT_CONFIG='{"modules":["git"],"git":{"commit_age_format":"raw"}}' uv run statuskit
```

**Step 2: Verify output**

Expected outputs should show:
- compact: `abc1234 Xd Yh Zm` or `abc1234 Yh Zm` etc.
- relative: `abc1234 X days Y hours ago` etc.
- raw: `abc1234 X hours ago` (original git format)

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Add `_parse_git_age` helper | git.py, test_git_module.py |
| 2 | Add `_decompose_minutes` helper | git.py, test_git_module.py |
| 3 | Update `_format_commit_age` with new logic | git.py, test_git_module.py |
| 4 | Manual testing | - |
