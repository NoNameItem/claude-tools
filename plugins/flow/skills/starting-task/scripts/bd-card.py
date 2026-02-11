#!/usr/bin/env python3
"""
Render task card from bd show --json output.

Usage:
    bd show <task-id> --json | python3 bd-card.py
"""

import unicodedata


def char_width(ch: str) -> int:
    """Return display width of a character (1 or 2)."""
    w = unicodedata.east_asian_width(ch)
    return 2 if w in ("W", "F") else 1


def str_width(s: str) -> int:
    """Return display width of a string."""
    return sum(char_width(ch) for ch in s)


CARD_WIDTH = 80
CONTENT_WIDTH = 76  # 80 - len("│ ") - len(" │")


def pad_right(s: str, width: int) -> str:
    """Pad string to exact display width with spaces."""
    current = str_width(s)
    if current >= width:
        return s
    return s + " " * (width - current)


def content_line(text: str) -> str:
    """Build a content line: │ <text padded to CONTENT_WIDTH> │"""
    return "│ " + pad_right(text, CONTENT_WIDTH) + " │"


def separator_line() -> str:
    """Build a separator: ├──...──┤"""
    return "├" + "─" * (CARD_WIDTH - 2) + "┤"


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap text to fit within width, respecting bullet and dependency indents."""
    if not text:
        return [""]

    # Detect indent for continuation lines
    indent = ""
    if text.startswith("- "):
        indent = "  "
    elif text.lstrip().startswith("→ "):
        # Indent to align after "→ " (preserve leading spaces + 2 more)
        leading = len(text) - len(text.lstrip())
        indent = " " * (leading + len("→ "))

    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        test = current + " " + word
        if str_width(test) <= width:
            current = test
        else:
            lines.append(current)
            current = indent + word

    lines.append(current)
    return lines


TYPE_WORDS = {
    "epic": "Epic",
    "feature": "Feature",
    "bug": "Bug",
    "task": "Task",
    "chore": "Chore",
}

DEP_TYPE_HEADERS = {
    "parent-child": "Parent:",
    "dependency": "Depends on:",
}


def top_border(type_word: str) -> str:
    """Build top border: ┌─ Type ──...──┐"""
    label = f" {type_word} "
    fill_width = CARD_WIDTH - 2 - str_width(label) - 1  # 2 for ┌ ┐, 1 for ─ before label
    return "┌─" + label + "─" * fill_width + "┐"


def bottom_border() -> str:
    """Build bottom border: └──...──┘"""
    return "└" + "─" * (CARD_WIDTH - 2) + "┘"


def extract_links(description: str) -> tuple[str, list[str]]:
    """Extract Design:/Plan:/Git: lines from description.

    Returns (cleaned_description, link_lines).
    Design: and Plan: go to links. Git: is removed but not shown.
    """
    links: list[str] = []
    clean_lines: list[str] = []

    for line in description.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("Design:", "Plan:")):
            links.append(stripped)
        elif stripped.startswith("Git:"):
            pass  # Remove from description, don't add to links
        else:
            clean_lines.append(line)

    # Remove trailing empty lines from cleaned description
    while clean_lines and not clean_lines[-1].strip():
        clean_lines.pop()

    return "\n".join(clean_lines), links


def render_title_section(title: str, issue_type: str) -> list[str]:
    """Render title section: top border with type word + title line(s)."""
    type_word = TYPE_WORDS.get(issue_type, issue_type.capitalize())
    lines = [top_border(type_word)]
    lines.extend(content_line(w) for w in wrap_text(title, CONTENT_WIDTH))
    return lines


def render_labels_section(labels: list[str]) -> list[str]:
    """Render labels as '#label1 #label2' with blank line before."""
    if not labels:
        return []
    label_text = " ".join(f"#{lbl}" for lbl in labels)
    lines = [content_line("")]  # blank line before labels
    lines.extend(content_line(w) for w in wrap_text(label_text, CONTENT_WIDTH))
    return lines


def render_metadata_section(task_id: str, priority: int, status: str, issue_type: str) -> list[str]:
    """Render metadata: ID, Priority, Status, Type."""
    return [
        separator_line(),
        content_line(f"ID: {task_id}"),
        content_line(f"Priority: P{priority}  Status: {status}  Type: {issue_type}"),
    ]


def render_description_section(description: str) -> list[str]:
    """Render description section. Returns [] if description is empty."""
    if not description or not description.strip():
        return []

    lines = [separator_line(), content_line("DESCRIPTION")]
    for text_line in description.split("\n"):
        lines.extend(content_line(w) for w in wrap_text(text_line, CONTENT_WIDTH))
    return lines


def render_links_section(links: list[str]) -> list[str]:
    """Render links section. Returns [] if no links."""
    if not links:
        return []

    lines = [separator_line(), content_line("LINKS")]
    for link in links:
        lines.extend(content_line(w) for w in wrap_text(link, CONTENT_WIDTH))
    return lines


def render_dependencies_section(deps: list[dict]) -> list[str]:
    """Render dependencies grouped by type. Returns [] if no deps."""
    if not deps:
        return []

    # Group by dependency_type
    groups: dict[str, list[dict]] = {}
    for dep in deps:
        dt = dep.get("dependency_type", "dependency")
        groups.setdefault(dt, []).append(dep)

    lines = [separator_line(), content_line("DEPENDENCIES")]
    for dep_type, group in groups.items():
        header = DEP_TYPE_HEADERS.get(dep_type, f"{dep_type}:")
        lines.append(content_line(header))
        for dep in group:
            dep_line = f"  → {dep['id']}: {dep['title']} ({dep['status']})"
            lines.extend(content_line(w) for w in wrap_text(dep_line, CONTENT_WIDTH))

    return lines
