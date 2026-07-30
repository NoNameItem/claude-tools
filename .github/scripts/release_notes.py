#!/usr/bin/env python3
"""Convert a GitHub release body (release-please markdown) to Telegram rich markup.

Nothing is computed between the tags: release-please already wrote finished notes into the
release body, so this is a pure format conversion — headings, list items, links, bold and
inline code, and nothing else. Anything unrecognised stays as an escaped paragraph.

The output is also bounded to Telegram's `sendRichMessage` limits (see `_TEXT_BUDGET` and
`_ELEMENT_BUDGET` below): if a release body would blow either budget, conversion stops at an
element boundary and a truncation marker is appended, rather than truncating the finished HTML
string (which could cut a tag in half and produce markup Telegram rejects).

Usage:
    gh api repos/{owner}/{repo}/releases/tags/{tag} --jq .body | python3 release_notes.py

Output (stdout):
    {"html": "<h2>…</h2>…"}  — or {} for an empty body, so the caller omits the block instead
    of rendering an empty <details>.
"""

from __future__ import annotations

import json
import re
import sys

_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")
_ITEM = re.compile(r"^[*-]\s+(?P<text>.*)$")
_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<url>[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(?P<text>[^*]+)\*\*")
_CODE = re.compile(r"`(?P<text>[^`]+)`")

# Telegram Bot API, "Rich Message Limits" (https://core.telegram.org/bots/api):
#   "Up to 32768 UTF-8 characters in the rich message text, including custom emoji alternative
#   text and formula source." Both limits count the *rendered* content, not the markup. 30000
#   leaves headroom under 32768 for the rest of the notification message that wraps these notes:
#   the heading, the verdict line, the Sonar block and the footer.
_TEXT_BUDGET = 30000
#   "Up to 500 blocks, including nested blocks, list items, ordered list items, table rows,
#   quotation blocks, and details blocks." 400 leaves headroom under 500 for the other blocks
#   (Sonar table, `<details>` wrapper) in the same message.
_ELEMENT_BUDGET = 400
_TRUNCATION_MARKER = "<p><i>Release notes truncated.</i></p>"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(text: str) -> str:
    """Escape a value for use inside a double-quoted HTML attribute (the `href` URL).

    `_esc` deliberately leaves `"` alone — it is not a text-content escape — so a link URL
    containing one (``[x](https://a"b)``) would otherwise close the `href="..."` attribute
    early and produce a malformed tag that `sendRichMessage` rejects, failing the notification.
    """
    return text.replace('"', "&quot;")


def _inline(text: str) -> str:
    """Escape, then apply the inline markdown Telegram's rich-markup parser understands."""
    out = _esc(text)
    out = _CODE.sub(lambda m: f"<code>{m.group('text')}</code>", out)
    out = _BOLD.sub(lambda m: f"<b>{m.group('text')}</b>", out)
    return _LINK.sub(lambda m: f'<a href="{_esc_attr(m.group("url"))}">{m.group("text")}</a>', out)


def _visible_length(text: str) -> int:
    """Length of the text as it will actually render: markdown syntax stripped, links reduced
    to their label. Used only to track the character budget while assembling — there is no
    plain-text output anymore, so this never builds a string for rendering.
    """
    stripped = _LINK.sub(lambda m: m.group("text"), text)
    stripped = _BOLD.sub(lambda m: m.group("text"), stripped)
    stripped = _CODE.sub(lambda m: m.group("text"), stripped)
    return len(stripped)


def convert(markdown: str | None) -> str:
    """Convert a release body to rich HTML.

    Returns ``""`` for an empty or whitespace-only body — a release with no notes must not
    produce an empty collapsible block.

    Bounded to `_TEXT_BUDGET` visible characters and `_ELEMENT_BUDGET` elements (see their
    definitions for where those numbers come from): both are tracked while assembling, and
    conversion stops at the next element boundary once either would be exceeded, appending
    `_TRUNCATION_MARKER` as the final element. Stopping during assembly — rather than truncating
    the finished HTML string — means the result can never end mid-tag.
    """
    if not markdown or not markdown.strip():
        return ""

    html_parts: list[str] = []
    in_list = False
    visible_len = 0
    element_count = 0
    truncated = False

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        heading = _HEADING.match(line)
        item = _ITEM.match(line)
        text = heading.group("text") if heading else item.group("text") if item else line

        # Budget for this element: the element itself, plus the `<ul>` container when an item
        # opens a new list (Telegram counts the list block itself, not just its items).
        elements_needed = 1 + (1 if item and not in_list else 0)
        if visible_len + _visible_length(text) > _TEXT_BUDGET or element_count + elements_needed > _ELEMENT_BUDGET:
            # Truncation is prefix-preserving: stop here rather than skipping this element and
            # continuing with the shorter ones after it. Release notes read top-down, so a
            # document silently missing a chunk from its middle is worse than one that visibly
            # ends early. The degenerate case — a first element that alone blows the budget —
            # therefore yields only the marker; release-please never emits a single element of
            # that size, and the notification still carries the Release button.
            truncated = True
            break

        if in_list and not item:
            html_parts.append("</ul>")
            in_list = False

        if heading:
            level = min(len(heading.group("hashes")), 3)
            html_parts.append(f"<h{level}>{_inline(heading.group('text'))}</h{level}>")
        elif item:
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_inline(item.group('text'))}</li>")
        else:
            html_parts.append(f"<p>{_inline(line)}</p>")

        visible_len += _visible_length(text)
        element_count += elements_needed

    if in_list:
        html_parts.append("</ul>")

    if truncated:
        html_parts.append(_TRUNCATION_MARKER)

    return "".join(html_parts)


def main() -> int:
    """CLI entrypoint. Always returns 0 — a release without notes is normal."""
    html = convert(sys.stdin.read())
    print(json.dumps({"html": html} if html else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
