"""Tests for bd-card.py."""

# ruff: noqa: INP001, S101, PLR2004, RUF003, RUF012

import importlib.util
from pathlib import Path

# Import bd-card.py as module (hyphenated filename)
_spec = importlib.util.spec_from_file_location("bd_card", Path(__file__).parent / "bd-card.py")
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

char_width = _mod.char_width
str_width = _mod.str_width
pad_right = _mod.pad_right
content_line = _mod.content_line
separator_line = _mod.separator_line

CARD_WIDTH = _mod.CARD_WIDTH  # 120
CONTENT_WIDTH = _mod.CONTENT_WIDTH  # 116
wrap_text = _mod.wrap_text
max_word_width = _mod.max_word_width
compute_card_width = _mod.compute_card_width
render_title_section = _mod.render_title_section
render_labels_section = _mod.render_labels_section
render_metadata_section = _mod.render_metadata_section
render_description_section = _mod.render_description_section
render_links_section = _mod.render_links_section
render_dependencies_section = _mod.render_dependencies_section
extract_links = _mod.extract_links

TYPE_WORDS = _mod.TYPE_WORDS
render_card = _mod.render_card


class TestCharWidth:
    def test_ascii(self):
        assert char_width("A") == 1

    def test_cyrillic(self):
        assert char_width("Я") == 1

    def test_cjk(self):
        assert char_width("\u4e16") == 2  # 世

    def test_fullwidth_letter(self):
        assert char_width("\uff21") == 2  # Ａ (fullwidth A)


class TestStrWidth:
    def test_ascii(self):
        assert str_width("hello") == 5

    def test_cyrillic(self):
        assert str_width("Привет") == 6

    def test_mixed(self):
        assert str_width("Hello Мир") == 9

    def test_empty(self):
        assert str_width("") == 0

    def test_cjk(self):
        assert str_width("世界") == 4


class TestPadRight:
    def test_ascii(self):
        result = pad_right("hello", 10)
        assert result == "hello     "
        assert str_width(result) == 10

    def test_cyrillic(self):
        result = pad_right("Привет", 10)
        assert result == "Привет    "
        assert str_width(result) == 10

    def test_exact_width(self):
        result = pad_right("hello", 5)
        assert result == "hello"

    def test_cjk_padding(self):
        result = pad_right("世界", 6)
        assert result == "世界  "
        assert str_width(result) == 6


class TestContentLine:
    def test_basic(self):
        line = content_line("hello")
        assert line.startswith("│ ")
        assert line.endswith(" │")
        assert str_width(line) == CARD_WIDTH

    def test_empty(self):
        line = content_line("")
        assert str_width(line) == CARD_WIDTH
        assert line == "│" + " " * (CARD_WIDTH - 2) + "│"


class TestSeparatorLine:
    def test_width(self):
        line = separator_line()
        assert str_width(line) == CARD_WIDTH
        assert line.startswith("├")
        assert line.endswith("┤")


class TestWrapText:
    def test_short_line_no_wrap(self):
        lines = wrap_text("short text", CONTENT_WIDTH)
        assert lines == ["short text"]

    def test_wrap_at_word_boundary(self):
        long = "word " * 20  # 100 chars
        lines = wrap_text(long.strip(), CONTENT_WIDTH)
        for line in lines:
            assert str_width(line) <= CONTENT_WIDTH

    def test_bullet_continuation_indent(self):
        """Lines starting with '- ' wrap with indent aligned to text after marker."""
        long_bullet = "- " + "word " * 20
        lines = wrap_text(long_bullet.strip(), CONTENT_WIDTH)
        assert lines[0].startswith("- ")
        for continuation in lines[1:]:
            assert continuation.startswith("  ")  # 2 spaces indent

    def test_dependency_continuation_indent(self):
        """Lines starting with '  → ' wrap with indent aligned to text after arrow."""
        long_dep = "  → claude-tools-lmr: " + "word " * 15
        lines = wrap_text(long_dep.rstrip(), CONTENT_WIDTH)
        # Continuation should indent to align after "→ "
        for continuation in lines[1:]:
            assert continuation.startswith("    ")  # 4 spaces

    def test_empty_string(self):
        assert wrap_text("", CONTENT_WIDTH) == [""]

    def test_cyrillic_wrap(self):
        long_cyrillic = "Слово " * 20
        lines = wrap_text(long_cyrillic.strip(), CONTENT_WIDTH)
        for line in lines:
            assert str_width(line) <= CONTENT_WIDTH
        assert len(lines) > 1


class TestTypeWords:
    def test_known_types(self):
        assert TYPE_WORDS["epic"] == "Epic"
        assert TYPE_WORDS["feature"] == "Feature"
        assert TYPE_WORDS["bug"] == "Bug"
        assert TYPE_WORDS["task"] == "Task"
        assert TYPE_WORDS["chore"] == "Chore"


class TestExtractLinks:
    def test_extracts_design_and_plan(self):
        desc = "Some text\nDesign: docs/plans/foo.md\nPlan: docs/plans/bar.md\nMore text"
        clean, links = extract_links(desc)
        assert "Design:" not in clean
        assert "Plan:" not in clean
        assert "More text" in clean
        assert len(links) == 2

    def test_removes_git_line_from_description(self):
        desc = "Some text\nGit: feature/branch-name\nMore text"
        clean, links = extract_links(desc)
        assert "Git:" not in clean
        assert len(links) == 0  # Git lines not shown in links

    def test_no_links(self):
        desc = "Simple description"
        clean, links = extract_links(desc)
        assert clean == "Simple description"
        assert links == []

    def test_multiple_design_lines(self):
        desc = "Design: foo.md\nDesign: bar.md"
        _clean, links = extract_links(desc)
        assert len(links) == 2


class TestRenderTitleSection:
    def test_top_border_contains_type_word(self):
        lines = render_title_section("Add dark mode", "feature")
        assert "Feature" in lines[0]
        assert lines[0].startswith("┌─")
        assert lines[0].endswith("┐")
        assert str_width(lines[0]) == CARD_WIDTH

    def test_title_line(self):
        lines = render_title_section("Add dark mode", "feature")
        assert any("Add dark mode" in line for line in lines)

    def test_unknown_type_fallback(self):
        lines = render_title_section("Some task", "milestone")
        # Should not crash, use type as-is capitalized
        assert lines[0].startswith("┌─")


class TestRenderMetadataSection:
    def test_contains_id_priority_status_type(self):
        lines = render_metadata_section("claude-tools-abc", 2, "open", "feature")
        text = "\n".join(lines)
        assert "claude-tools-abc" in text
        assert "P2" in text
        assert "open" in text
        assert "feature" in text


class TestRenderDescriptionSection:
    def test_includes_header_and_text(self):
        lines = render_description_section("Some description text")
        text = "\n".join(lines)
        assert "DESCRIPTION" in text
        assert "Some description" in text

    def test_empty_returns_empty(self):
        lines = render_description_section("")
        assert lines == []

    def test_whitespace_only_returns_empty(self):
        lines = render_description_section("   \n  \n  ")
        assert lines == []


class TestRenderLinksSection:
    def test_includes_header_and_links(self):
        links = ["Design: docs/plans/foo.md", "Plan: docs/plans/bar.md"]
        lines = render_links_section(links)
        text = "\n".join(lines)
        assert "LINKS" in text
        assert "Design:" in text
        assert "Plan:" in text

    def test_empty_returns_empty(self):
        assert render_links_section([]) == []


class TestRenderDependenciesSection:
    def test_parent_child(self):
        deps = [{"id": "proj-elf", "title": "Flow Improvements", "status": "open", "dependency_type": "parent-child"}]
        lines = render_dependencies_section(deps)
        text = "\n".join(lines)
        assert "DEPENDENCIES" in text
        assert "Parent:" in text
        assert "proj-elf" in text

    def test_dependency_type(self):
        deps = [{"id": "proj-abc", "title": "Some task", "status": "closed", "dependency_type": "dependency"}]
        lines = render_dependencies_section(deps)
        text = "\n".join(lines)
        assert "Depends on:" in text

    def test_empty_returns_empty(self):
        assert render_dependencies_section([]) == []

    def test_multiple_groups(self):
        deps = [
            {"id": "proj-a", "title": "Parent", "status": "open", "dependency_type": "parent-child"},
            {"id": "proj-b", "title": "Blocker", "status": "open", "dependency_type": "dependency"},
        ]
        lines = render_dependencies_section(deps)
        text = "\n".join(lines)
        assert "Parent:" in text
        assert "Depends on:" in text


class TestMaxWordWidth:
    def test_simple(self):
        assert max_word_width("hello world") == 5

    def test_long_url(self):
        url = "https://example.com/very/long/path/to/resource"
        assert max_word_width(f"Link: {url}") == str_width(url)

    def test_empty(self):
        assert max_word_width("") == 0

    def test_single_word(self):
        assert max_word_width("superlongword") == 13


class TestComputeCardWidth:
    def test_normal_task_returns_default(self):
        task = {
            "id": "proj-abc",
            "title": "Short title",
            "description": "Short description",
            "status": "open",
            "labels": [],
            "dependencies": [],
        }
        assert compute_card_width(task) == CARD_WIDTH

    def test_long_word_expands_width(self):
        long_word = "a" * 200
        task = {
            "id": "proj-abc",
            "title": f"Title with {long_word} inside",
            "description": "",
            "status": "open",
            "labels": [],
            "dependencies": [],
        }
        assert compute_card_width(task) == 200 + 4  # word + borders

    def test_long_description_word_expands(self):
        long_url = "https://example.com/" + "x" * 150
        task = {
            "id": "proj-abc",
            "title": "Short",
            "description": f"See {long_url} for details",
            "status": "open",
            "labels": [],
            "dependencies": [],
        }
        assert compute_card_width(task) == str_width(long_url) + 4

    def test_metadata_line_expands(self):
        long_status = "s" * 200
        task = {
            "id": "proj-abc",
            "title": "Short",
            "description": "",
            "status": long_status,
            "labels": [],
            "dependencies": [],
        }
        meta = f"Priority: P2  Status: {long_status}  Type: task"
        assert compute_card_width(task) == str_width(meta) + 4


class TestRenderCard:
    """Integration tests for full card rendering."""

    FULL_TASK = {
        "id": "claude-tools-xhz",
        "title": "Улучшить отображение текущей задачи в flow:starting-task",
        "description": (
            "Сейчас текущая задача выводится в рамке, которая выглядит непонятно.\n"
            "Нужно продумать более удачный формат отображения.\n"
            "\n"
            "TODO:\n"
            "- Проанализировать текущий вывод\n"
            "- Продумать альтернативные варианты отображения\n"
            "- Реализовать выбранный вариант\n"
            "\n"
            "Design: docs/plans/2026-02-10-task-card-script-design.md"
        ),
        "status": "in_progress",
        "priority": 4,
        "issue_type": "task",
        "labels": ["flow"],
        "dependencies": [
            {
                "id": "claude-tools-elf",
                "title": "Flow Improvements",
                "status": "open",
                "dependency_type": "parent-child",
            }
        ],
    }

    MINIMAL_TASK = {
        "id": "claude-tools-abc",
        "title": "Add dark mode support",
        "description": "",
        "status": "open",
        "priority": 2,
        "issue_type": "feature",
        "labels": [],
        "dependencies": [],
    }

    def test_all_lines_same_width(self):
        """Every line in the card must have the same visual width."""
        output = render_card(self.FULL_TASK)
        lines = output.split("\n")
        for line in lines:
            assert str_width(line) == CARD_WIDTH, f"Line width {str_width(line)} != {CARD_WIDTH}: {line!r}"

    def test_minimal_card_all_lines_same_width(self):
        output = render_card(self.MINIMAL_TASK)
        lines = output.split("\n")
        for line in lines:
            assert str_width(line) == CARD_WIDTH, f"Line width {str_width(line)} != {CARD_WIDTH}: {line!r}"

    def test_full_card_has_all_sections(self):
        output = render_card(self.FULL_TASK)
        assert "Task" in output  # type word in border
        assert "claude-tools-xhz" in output  # ID
        assert "#flow" in output  # label
        assert "DESCRIPTION" in output
        assert "LINKS" in output
        assert "Design:" in output
        assert "DEPENDENCIES" in output
        assert "Parent:" in output

    def test_minimal_card_omits_optional_sections(self):
        output = render_card(self.MINIMAL_TASK)
        assert "DESCRIPTION" not in output
        assert "LINKS" not in output
        assert "DEPENDENCIES" not in output

    def test_design_line_removed_from_description(self):
        output = render_card(self.FULL_TASK)
        # Design line should be in LINKS, not in DESCRIPTION
        lines = output.split("\n")
        in_desc = False
        for line in lines:
            if "DESCRIPTION" in line:
                in_desc = True
            if "LINKS" in line:
                in_desc = False
            if in_desc and "Design:" in line:
                msg = "Design: line found in DESCRIPTION section"
                raise AssertionError(msg)

    def test_git_line_not_shown(self):
        task = dict(self.FULL_TASK)
        task["description"] = "Text\nGit: feature/branch\nMore text"
        output = render_card(task)
        assert "Git:" not in output

    def test_starts_with_top_border(self):
        output = render_card(self.FULL_TASK)
        assert output.startswith("┌─")

    def test_ends_with_bottom_border(self):
        output = render_card(self.FULL_TASK)
        assert output.strip().endswith("┘")

    def test_dynamic_width_all_lines_same_width(self):
        """Card with overlong word expands — all lines must still align."""
        long_url = "https://example.com/" + "x" * 150
        task = {
            "id": "proj-abc",
            "title": "Short title",
            "description": f"See {long_url} for details",
            "status": "open",
            "priority": 2,
            "issue_type": "feature",
            "labels": [],
            "dependencies": [],
        }
        output = render_card(task)
        lines = output.split("\n")
        expected_width = str_width(long_url) + 4
        for line in lines:
            assert str_width(line) == expected_width, f"Line width {str_width(line)} != {expected_width}: {line!r}"
