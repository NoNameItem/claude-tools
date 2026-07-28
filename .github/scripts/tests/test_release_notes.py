"""Tests for release_notes.py markdown conversion."""

from __future__ import annotations

import pytest

from ..release_notes import _ELEMENT_BUDGET, _TEXT_BUDGET, _TRUNCATION_MARKER, convert

REAL_BODY = """\
## [0.5.0](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.4.0...statuskit-0.5.0) (2026-07-21)

### Features

* **statuskit:** dynamic per-model usage limits ([#112](https://github.com/NoNameItem/claude-tools/pull/112)) ([291b32e](https://github.com/NoNameItem/claude-tools/commit/291b32e))
"""


class TestConvert:
    def test_headings(self) -> None:
        html = convert("## 0.5.0\n### Features\n")
        assert html == "<h2>0.5.0</h2><h3>Features</h3>"

    def test_list_items_are_wrapped_once(self) -> None:
        html = convert("* one\n* two\n")
        assert html == "<ul><li>one</li><li>two</li></ul>"

    def test_list_closes_before_a_heading(self) -> None:
        html = convert("* one\n### Bug Fixes\n* two\n")
        assert html == "<ul><li>one</li></ul><h3>Bug Fixes</h3><ul><li>two</li></ul>"

    def test_links_and_bold_and_code(self) -> None:
        html = convert("* **statuskit:** see [#112](https://x) and `foo`\n")
        assert html == '<ul><li><b>statuskit:</b> see <a href="https://x">#112</a> and <code>foo</code></li></ul>'

    def test_escapes_html(self) -> None:
        html = convert("* fix <T> & <U>\n")
        assert html == "<ul><li>fix &lt;T&gt; &amp; &lt;U&gt;</li></ul>"

    def test_quote_in_link_url_is_escaped(self) -> None:
        """A `"` in the URL must not close the `href="..."` attribute early — see release_notes.py
        `_esc_attr`. Otherwise the tag is malformed and `sendRichMessage` rejects the message.
        """
        html = convert('* [x](https://a"b)\n')
        assert html == '<ul><li><a href="https://a&quot;b">x</a></li></ul>'
        assert '"b">' not in html

    @pytest.mark.parametrize("body", ["", "   \n\n", None])
    def test_empty_body(self, body: str | None) -> None:
        assert convert(body) == ""

    def test_real_release_body(self) -> None:
        html = convert(REAL_BODY)
        assert html.startswith('<h2><a href="https://github.com/NoNameItem/claude-tools/compare/')
        assert "<h3>Features</h3>" in html
        assert "<b>statuskit:</b>" in html


class TestBudgets:
    def test_under_budget_passes_through_unchanged(self) -> None:
        html = convert(REAL_BODY)
        assert _TRUNCATION_MARKER not in html
        assert html.startswith('<h2><a href="https://github.com/NoNameItem/claude-tools/compare/')

    def test_over_character_budget_is_truncated(self) -> None:
        # 40 items of 1000 chars each = 40000 visible chars, well over _TEXT_BUDGET (30000),
        # while only 41 elements (list + items), nowhere near _ELEMENT_BUDGET (400) — isolates
        # the character-budget path.
        item_text = "x" * 1000
        markdown = "\n".join(f"* {item_text}" for _ in range(40))
        html = convert(markdown)

        assert html.endswith(_TRUNCATION_MARKER)
        visible_chars = html.count("x")
        assert visible_chars <= _TEXT_BUDGET
        assert html.count("<li>") < 40  # stopped before consuming all 40 items

    def test_over_element_budget_is_truncated(self) -> None:
        # 450 one-character items: element count (list + items) exceeds _ELEMENT_BUDGET (400)
        # long before visible text gets anywhere near _TEXT_BUDGET (30000) — isolates the
        # element-budget path.
        markdown = "\n".join(f"* i{n}" for n in range(450))
        html = convert(markdown)

        assert html.endswith(_TRUNCATION_MARKER)
        assert html.count("<li>") <= _ELEMENT_BUDGET

    def test_truncated_html_is_well_formed(self) -> None:
        markdown = "\n".join(f"* i{n}" for n in range(450))
        html = convert(markdown)

        assert html.endswith(_TRUNCATION_MARKER)
        assert html.count("<ul>") == html.count("</ul>")
        assert html.count("<li>") == html.count("</li>")
        # The list must be closed before the truncation marker is appended, not left dangling.
        body_before_marker = html[: -len(_TRUNCATION_MARKER)]
        assert body_before_marker.endswith("</ul>")
