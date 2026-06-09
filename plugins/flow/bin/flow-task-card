#!/usr/bin/env python3
"""
Render task card from bd show --json output.

Usage:
    bd show <task-id> --json | python3 bd-card.py
"""

import json
import sys
import unicodedata


def char_width(ch: str) -> int:
    """Return display width of a character (1 or 2)."""
    w = unicodedata.east_asian_width(ch)
    return 2 if w in ("W", "F") else 1


def str_width(s: str) -> int:
    """Return display width of a string."""
    return sum(char_width(ch) for ch in s)


CARD_WIDTH = 120
CONTENT_WIDTH = 116  # 120 - len("│ ") - len(" │")


def pad_right(s: str, width: int) -> str:
    """Pad string to exact display width with spaces."""
    current = str_width(s)
    if current >= width:
        return s
    return s + " " * (width - current)


def content_line(text: str, card_width: int = CARD_WIDTH) -> str:
    """Build a content line: │ <text padded to content_width> │"""
    content_width = card_width - 4
    return "│ " + pad_right(text, content_width) + " │"


def separator_line(card_width: int = CARD_WIDTH) -> str:
    """Build a separator: ├──...──┤"""
    return "├" + "─" * (card_width - 2) + "┤"


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


def top_border(type_word: str, card_width: int = CARD_WIDTH) -> str:
    """Build top border: ┌─ Type ──...──┐"""
    label = f" {type_word} "
    fill_width = card_width - 2 - str_width(label) - 1  # 2 for ┌ ┐, 1 for ─ before label
    return "┌─" + label + "─" * fill_width + "┐"


def bottom_border(card_width: int = CARD_WIDTH) -> str:
    """Build bottom border: └──...──┘"""
    return "└" + "─" * (card_width - 2) + "┘"


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


def render_title_section(title: str, issue_type: str, card_width: int = CARD_WIDTH) -> list[str]:
    """Render title section: top border with type word + title line(s)."""
    content_width = card_width - 4
    type_word = TYPE_WORDS.get(issue_type, issue_type.capitalize())
    lines = [top_border(type_word, card_width)]
    lines.extend(content_line(w, card_width) for w in wrap_text(title, content_width))
    return lines


def render_labels_section(labels: list[str], card_width: int = CARD_WIDTH) -> list[str]:
    """Render labels as '#label1 #label2' with blank line before."""
    content_width = card_width - 4
    if not labels:
        return []
    label_text = " ".join(f"#{lbl}" for lbl in labels)
    lines = [content_line("", card_width)]  # blank line before labels
    lines.extend(content_line(w, card_width) for w in wrap_text(label_text, content_width))
    return lines


def render_metadata_section(
    task_id: str, priority: int, status: str, issue_type: str, card_width: int = CARD_WIDTH
) -> list[str]:
    """Render metadata: ID, Priority, Status, Type."""
    return [
        separator_line(card_width),
        content_line(f"ID: {task_id}", card_width),
        content_line(f"Priority: P{priority}  Status: {status}  Type: {issue_type}", card_width),
    ]


def render_description_section(description: str, card_width: int = CARD_WIDTH) -> list[str]:
    """Render description section. Returns [] if description is empty."""
    content_width = card_width - 4
    if not description or not description.strip():
        return []

    lines = [separator_line(card_width), content_line("DESCRIPTION", card_width)]
    for text_line in description.split("\n"):
        lines.extend(content_line(w, card_width) for w in wrap_text(text_line, content_width))
    return lines


def render_links_section(links: list[str], card_width: int = CARD_WIDTH) -> list[str]:
    """Render links section. Returns [] if no links."""
    content_width = card_width - 4
    if not links:
        return []

    lines = [separator_line(card_width), content_line("LINKS", card_width)]
    for link in links:
        lines.extend(content_line(w, card_width) for w in wrap_text(link, content_width))
    return lines


def render_dependencies_section(deps: list[dict], card_width: int = CARD_WIDTH) -> list[str]:
    """Render dependencies grouped by type. Returns [] if no deps."""
    content_width = card_width - 4
    if not deps:
        return []

    # Group by dependency_type
    groups: dict[str, list[dict]] = {}
    for dep in deps:
        dt = dep.get("dependency_type", "dependency")
        groups.setdefault(dt, []).append(dep)

    lines = [separator_line(card_width), content_line("DEPENDENCIES", card_width)]
    for dep_type, group in groups.items():
        header = DEP_TYPE_HEADERS.get(dep_type, f"{dep_type}:")
        lines.append(content_line(header, card_width))
        for dep in group:
            dep_line = f"  → {dep['id']}: {dep['title']} ({dep['status']})"
            lines.extend(content_line(w, card_width) for w in wrap_text(dep_line, content_width))

    return lines


def max_word_width(text: str) -> int:
    """Return display width of the longest space-delimited word."""
    if not text:
        return 0
    return max((str_width(w) for w in text.split()), default=0)


def compute_card_width(task: dict) -> int:
    """Compute minimum card width to fit all content without breaking words.

    Scans all text in the task and returns max(CARD_WIDTH, longest_word + 4).
    The +4 accounts for border characters: "│ " (2) + " │" (2).
    """
    max_w = 0

    # Title
    max_w = max(max_w, max_word_width(task.get("title", "")))

    # Labels
    for lbl in task.get("labels", []):
        max_w = max(max_w, str_width(f"#{lbl}"))

    # Metadata (not wrapped, check full line widths)
    task_id = task.get("id", "")
    max_w = max(max_w, str_width(f"ID: {task_id}"))
    priority = task.get("priority", 2)
    status = task.get("status", "")
    issue_type = task.get("issue_type", "task")
    meta = f"Priority: P{priority}  Status: {status}  Type: {issue_type}"
    max_w = max(max_w, str_width(meta))

    # Description (after link extraction)
    raw_desc = task.get("description", "")
    clean_desc, links = extract_links(raw_desc)
    for line in clean_desc.split("\n"):
        max_w = max(max_w, max_word_width(line))

    # Links
    for link in links:
        max_w = max(max_w, max_word_width(link))

    # Dependencies
    for dep in task.get("dependencies", []):
        dep_line = f"  → {dep['id']}: {dep['title']} ({dep['status']})"
        max_w = max(max_w, max_word_width(dep_line))

    return max(CARD_WIDTH, max_w + 4)


def render_card(task: dict) -> str:
    """Render a full task card from a task dict."""
    card_width = compute_card_width(task)
    lines: list[str] = []

    # Title section (always)
    lines.extend(render_title_section(task["title"], task.get("issue_type", "task"), card_width))

    # Labels (if present)
    lines.extend(render_labels_section(task.get("labels", []), card_width))

    # Metadata (always)
    lines.extend(
        render_metadata_section(
            task["id"],
            task.get("priority", 2),
            task["status"],
            task.get("issue_type", "task"),
            card_width,
        )
    )

    # Extract links from description
    raw_desc = task.get("description", "")
    clean_desc, links = extract_links(raw_desc)

    # Description (if non-empty after link removal)
    lines.extend(render_description_section(clean_desc, card_width))

    # Links (if any Design:/Plan: found)
    lines.extend(render_links_section(links, card_width))

    # Dependencies (if any)
    lines.extend(render_dependencies_section(task.get("dependencies", []), card_width))

    # Bottom border
    lines.append(bottom_border(card_width))

    return "\n".join(lines)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("No task data.", file=sys.stderr)
        sys.exit(1)

    # bd show --json returns an array, use first element
    task = data[0] if isinstance(data, list) else data
    print(render_card(task))


if __name__ == "__main__":
    main()
