"""Tests for release_notes.py markdown conversion."""

from __future__ import annotations

import pytest

from ..release_notes import convert

REAL_BODY = """\
## [0.5.0](https://github.com/NoNameItem/claude-tools/compare/statuskit-0.4.0...statuskit-0.5.0) (2026-07-21)

### Features

* **statuskit:** dynamic per-model usage limits ([#112](https://github.com/NoNameItem/claude-tools/pull/112)) ([291b32e](https://github.com/NoNameItem/claude-tools/commit/291b32e))
"""


class TestConvert:
    def test_headings(self) -> None:
        html, _ = convert("## 0.5.0\n### Features\n")
        assert html == "<h2>0.5.0</h2><h3>Features</h3>"

    def test_list_items_are_wrapped_once(self) -> None:
        html, _ = convert("* one\n* two\n")
        assert html == "<ul><li>one</li><li>two</li></ul>"

    def test_list_closes_before_a_heading(self) -> None:
        html, _ = convert("* one\n### Bug Fixes\n* two\n")
        assert html == "<ul><li>one</li></ul><h3>Bug Fixes</h3><ul><li>two</li></ul>"

    def test_links_and_bold_and_code(self) -> None:
        html, _ = convert("* **statuskit:** see [#112](https://x) and `foo`\n")
        assert html == '<ul><li><b>statuskit:</b> see <a href="https://x">#112</a> and <code>foo</code></li></ul>'

    def test_escapes_html(self) -> None:
        html, _ = convert("* fix <T> & <U>\n")
        assert html == "<ul><li>fix &lt;T&gt; &amp; &lt;U&gt;</li></ul>"

    def test_quote_in_link_url_is_escaped(self) -> None:
        """A `"` in the URL must not close the `href="..."` attribute early — see release_notes.py
        `_esc_attr`. Otherwise the tag is malformed and `sendRichMessage` rejects the message.
        """
        html, _ = convert('* [x](https://a"b)\n')
        assert html == '<ul><li><a href="https://a&quot;b">x</a></li></ul>'
        assert '"b">' not in html

    def test_plain_rendering_has_no_block_tags(self) -> None:
        _, plain = convert(REAL_BODY)
        for tag in ("<h2", "<h3", "<ul", "<li"):
            assert tag not in plain
        assert plain.splitlines()[0].startswith("0.5.0")
        assert "• " in plain

    @pytest.mark.parametrize("body", ["", "   \n\n", None])
    def test_empty_body(self, body: str | None) -> None:
        assert convert(body) == ("", "")

    def test_real_release_body(self) -> None:
        html, _ = convert(REAL_BODY)
        assert html.startswith('<h2><a href="https://github.com/NoNameItem/claude-tools/compare/')
        assert "<h3>Features</h3>" in html
        assert "<b>statuskit:</b>" in html
