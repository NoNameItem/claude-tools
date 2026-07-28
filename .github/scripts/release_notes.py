#!/usr/bin/env python3
"""Convert a GitHub release body (release-please markdown) to Telegram rich markup.

Nothing is computed between the tags: release-please already wrote finished notes into the
release body, so this is a pure format conversion — headings, list items, links, bold and
inline code, and nothing else. Anything unrecognised stays as an escaped paragraph.

Usage:
    gh api repos/{owner}/{repo}/releases/tags/{tag} --jq .body | python3 release_notes.py

Output (stdout):
    {"html": "<h2>…</h2>…", "plain": "…"}  — or {} for an empty body, so the caller omits
    the block instead of rendering an empty <details>.
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


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(text: str) -> str:
    """Escape a value for use inside a double-quoted HTML attribute (the `href` URL).

    `_esc` deliberately leaves `"` alone — it is not a text-content escape — so a link URL
    containing one (``[x](https://a"b)``) would otherwise close the `href="..."` attribute
    early and produce a malformed tag that `sendRichMessage` rejects, degrading the whole
    notification to the plain fallback.
    """
    return text.replace('"', "&quot;")


def _inline(text: str) -> str:
    """Escape, then apply the inline markdown both Telegram parsers understand."""
    out = _esc(text)
    out = _CODE.sub(lambda m: f"<code>{m.group('text')}</code>", out)
    out = _BOLD.sub(lambda m: f"<b>{m.group('text')}</b>", out)
    return _LINK.sub(lambda m: f'<a href="{_esc_attr(m.group("url"))}">{m.group("text")}</a>', out)


def _strip_inline(text: str) -> str:
    """Plain-text form: keep the words, drop the markup (links become their label)."""
    out = _LINK.sub(lambda m: m.group("text"), text)
    out = _BOLD.sub(lambda m: m.group("text"), out)
    return _CODE.sub(lambda m: m.group("text"), out)


def convert(markdown: str | None) -> tuple[str, str]:
    """Convert a release body to ``(rich_html, plain_text)``.

    Returns ``("", "")`` for an empty or whitespace-only body — a release with no notes must
    not produce an empty collapsible block.
    """
    if not markdown or not markdown.strip():
        return ("", "")

    html_parts: list[str] = []
    plain_lines: list[str] = []
    in_list = False

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        heading = _HEADING.match(line)
        item = _ITEM.match(line)

        if in_list and not item:
            html_parts.append("</ul>")
            in_list = False

        if heading:
            level = min(len(heading.group("hashes")), 3)
            html_parts.append(f"<h{level}>{_inline(heading.group('text'))}</h{level}>")
            plain_lines.append(_strip_inline(heading.group("text")))
        elif item:
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_inline(item.group('text'))}</li>")
            plain_lines.append(f"• {_strip_inline(item.group('text'))}")
        else:
            html_parts.append(f"<p>{_inline(line)}</p>")
            plain_lines.append(_strip_inline(line))

    if in_list:
        html_parts.append("</ul>")

    return ("".join(html_parts), "\n".join(plain_lines))


def main() -> int:
    """CLI entrypoint. Always returns 0 — a release without notes is normal."""
    html, plain = convert(sys.stdin.read())
    print(json.dumps({"html": html, "plain": plain} if html else {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
