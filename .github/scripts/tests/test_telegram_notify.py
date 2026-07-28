"""Golden-output tests for telegram_notify.py rendering."""

from __future__ import annotations

import pytest

from ..telegram_notify import esc, icon_for, render_plain, render_rich

CHECKS_BLOCK = {
    "type": "table",
    "title": "All checks passed",
    "open": False,
    "rows": [
        ["Validate PR", {"text": "✅", "align": "center"}],
        ["review-gate", {"text": "✅", "align": "center"}],
    ],
}


def _spec(**overrides) -> dict:
    spec = {
        "status": "ready",
        "title": "Add the quota module",
        "verdict": [{"text": "Ready to merge"}],
        "blocks": [CHECKS_BLOCK],
        "footer": "claude-tools · PR 118",
        "buttons": [{"text": "Pull request", "url": "https://github.com/o/r/pull/118"}],
        "silent": False,
        "reply_to": None,
    }
    spec.update(overrides)
    return spec


class TestEsc:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a & b", "a &amp; b"),
            ("<script>", "&lt;script&gt;"),
            ("Fix <T> & <U>", "Fix &lt;T&gt; &amp; &lt;U&gt;"),
            ("", ""),
        ],
    )
    def test_escapes(self, raw: str, expected: str) -> None:
        assert esc(raw) == expected


class TestIconFor:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("started", "🚀"),
            ("ready", "✅"),
            ("comments", "⚠️"),
            ("failed", "❌"),
            ("cancelled", "⛔"),
            ("released", "📦"),
            ("nonsense", "❓"),
        ],
    )
    def test_icons(self, status: str, expected: str) -> None:
        assert icon_for(status) == expected


class TestRenderRich:
    def test_ready(self) -> None:
        assert render_rich(_spec()) == (
            "<h1>✅ Add the quota module</h1>"
            "<p>Ready to merge</p>"
            "<details><summary>All checks passed</summary><table bordered>"
            '<tr><td>Validate PR</td><td align="center">✅</td></tr>'
            '<tr><td>review-gate</td><td align="center">✅</td></tr>'
            "</table></details>"
            "<footer>claude-tools · PR 118</footer>"
        )

    def test_failed_table_is_bare_and_jobs_are_open(self) -> None:
        spec = _spec(
            status="failed",
            verdict=[{"text": "Checks failed: "}, {"text": "review-gate", "bold": True}],
            blocks=[
                {
                    "type": "table",
                    "rows": [[{"text": "review-gate", "bold": True}, {"text": "❌", "align": "center"}]],
                },
                {
                    "type": "list",
                    "title": "Failed jobs: 1",
                    "open": True,
                    "items": [[{"text": "SonarCloud (statuskit)", "bold": True}, {"text": " — Quality Gate failed"}]],
                },
            ],
        )
        assert render_rich(spec) == (
            "<h1>❌ Add the quota module</h1>"
            "<p>Checks failed: <b>review-gate</b></p>"
            "<table bordered>"
            '<tr><td><b>review-gate</b></td><td align="center">❌</td></tr>'
            "</table>"
            "<details open><summary>Failed jobs: 1</summary><ul>"
            "<li><b>SonarCloud (statuskit)</b> — Quality Gate failed</li>"
            "</ul></details>"
            "<footer>claude-tools · PR 118</footer>"
        )

    def test_green_notification_has_no_bold(self) -> None:
        assert "<b>" not in render_rich(_spec())

    def test_comments_verdict(self) -> None:
        spec = _spec(status="comments", verdict=[{"text": "All checks passed, unresolved comments: 3"}])
        rendered = render_rich(spec)
        assert rendered.startswith("<h1>⚠️ Add the quota module</h1><p>All checks passed, unresolved comments: 3</p>")
        assert "<b>" not in rendered  # unresolved comments are not a failure

    def test_started_verdict_has_no_blocks(self) -> None:
        spec = _spec(status="started", verdict=[{"text": "PR updated, checks running"}], blocks=[])
        assert render_rich(spec) == (
            "<h1>🚀 Add the quota module</h1><p>PR updated, checks running</p><footer>claude-tools · PR 118</footer>"
        )

    def test_cancelled_verdict(self) -> None:
        spec = _spec(status="cancelled", verdict=[{"text": "Run cancelled"}], blocks=[])
        assert render_rich(spec).startswith("<h1>⛔ Add the quota module</h1>")

    def test_block_link_is_a_paragraph_after_the_table(self) -> None:
        spec = _spec(
            blocks=[
                {
                    "type": "table",
                    "title": "Sonar · statuskit — project state",
                    "open": False,
                    "rows": [["Coverage", "93.4%"]],
                    "link": {"text": "Dashboard", "url": "https://sonarcloud.io/x"},
                }
            ]
        )
        assert (
            "<details><summary>Sonar · statuskit — project state</summary>"
            "<table bordered><tr><td>Coverage</td><td>93.4%</td></tr></table>"
            '<p><a href="https://sonarcloud.io/x">Dashboard</a></p></details>' in render_rich(spec)
        )

    def test_code_segment(self) -> None:
        spec = _spec(
            status="started",
            verdict=[{"text": "New commit "}, {"text": "a1b2c3d", "code": True}, {"text": ", checks running"}],
            blocks=[],
        )
        assert "<p>New commit <code>a1b2c3d</code>, checks running</p>" in render_rich(spec)

    def test_html_block_is_passed_through(self) -> None:
        spec = _spec(
            blocks=[
                {
                    "type": "html",
                    "title": "Release notes",
                    "open": True,
                    "html": "<h2>0.5.0</h2>",
                    "plain": "0.5.0",
                }
            ]
        )
        assert "<details open><summary>Release notes</summary><h2>0.5.0</h2></details>" in render_rich(spec)

    def test_untitled_block_is_bare(self) -> None:
        spec = _spec(blocks=[{"type": "table", "rows": [["a", "b"]]}])
        rendered = render_rich(spec)
        assert "<details" not in rendered
        assert "<table bordered><tr><td>a</td><td>b</td></tr></table>" in rendered

    def test_title_is_escaped(self) -> None:
        assert "<h1>✅ Fix &lt;T&gt; &amp; U</h1>" in render_rich(_spec(title="Fix <T> & U"))

    def test_no_verdict_no_paragraph(self) -> None:
        assert "<p>" not in render_rich(_spec(verdict=[], blocks=[]))


class TestRenderPlain:
    def test_ready(self) -> None:
        assert render_plain(_spec()) == (
            "<b>✅ Add the quota module</b>\n"
            "Ready to merge\n"
            "\n"
            "<b>All checks passed</b>\n"
            "<blockquote expandable>Validate PR — ✅\n"
            "review-gate — ✅</blockquote>\n"
            "\n"
            '<a href="https://github.com/o/r/pull/118">Pull request</a>\n'
            "claude-tools · PR 118"
        )

    def test_block_link_becomes_a_line_in_the_quote(self) -> None:
        spec = _spec(
            blocks=[
                {
                    "type": "table",
                    "title": "Sonar · statuskit — project state",
                    "rows": [["Coverage", "93.4%"]],
                    "link": {"text": "Dashboard", "url": "https://sonarcloud.io/x"},
                }
            ]
        )
        assert (
            "<blockquote expandable>Coverage — 93.4%\n"
            '<a href="https://sonarcloud.io/x">Dashboard</a></blockquote>' in render_plain(spec)
        )

    def test_comments_verdict(self) -> None:
        spec = _spec(status="comments", verdict=[{"text": "All checks passed, unresolved comments: 3"}], blocks=[])
        assert render_plain(spec).splitlines()[:2] == [
            "<b>⚠️ Add the quota module</b>",
            "All checks passed, unresolved comments: 3",
        ]

    def test_started_has_no_blocks(self) -> None:
        spec = _spec(
            status="started",
            verdict=[{"text": "New commit "}, {"text": "a1b2c3d", "code": True}, {"text": ", checks running"}],
            blocks=[],
        )
        assert render_plain(spec) == (
            "<b>🚀 Add the quota module</b>\n"
            "New commit <code>a1b2c3d</code>, checks running\n"
            "\n"
            '<a href="https://github.com/o/r/pull/118">Pull request</a>\n'
            "claude-tools · PR 118"
        )

    def test_failed_keeps_bold(self) -> None:
        spec = _spec(
            status="failed",
            verdict=[{"text": "Checks failed: "}, {"text": "review-gate", "bold": True}],
            blocks=[],
        )
        assert render_plain(spec).splitlines()[1] == "Checks failed: <b>review-gate</b>"

    def test_no_rich_tags_leak(self) -> None:
        spec = _spec(
            blocks=[
                CHECKS_BLOCK,
                {"type": "list", "title": "Failed jobs", "items": [["SonarCloud (statuskit)"]]},
                {"type": "html", "title": "Release notes", "html": "<h2>0.5.0</h2>", "plain": "0.5.0"},
            ]
        )
        rendered = render_plain(spec)
        for tag in ("<h1", "<h2", "<table", "<details", "<summary", "<ul", "<li", "<footer", "<p>"):
            assert tag not in rendered

    def test_list_items_become_bullets(self) -> None:
        spec = _spec(blocks=[{"type": "list", "title": "Failed jobs", "items": [["a"], ["b"]]}])
        assert "<blockquote expandable>• a\n• b</blockquote>" in render_plain(spec)

    def test_two_buttons_join_with_middot(self) -> None:
        spec = _spec(
            buttons=[
                {"text": "Pull request", "url": "https://p"},
                {"text": "Checks", "url": "https://c"},
            ]
        )
        assert '<a href="https://p">Pull request</a> · <a href="https://c">Checks</a>' in render_plain(spec)


def test_html_body_is_trusted_but_plain_body_is_escaped() -> None:
    """`html` arrives pre-escaped from release_notes._inline; `plain` arrives raw from
    release_notes._strip_inline and must be escaped here, or `<`/`>`/`&` in it would corrupt the
    sendMessage HTML parse.
    """
    spec = _spec(
        blocks=[
            {
                "type": "html",
                "title": "Release notes",
                "html": "<h2>0.5.0 &lt;beta&gt;</h2>",
                "plain": "0.5.0 <beta> & more",
            }
        ]
    )
    assert "<h2>0.5.0 &lt;beta&gt;</h2>" in render_rich(spec)
    assert "0.5.0 &lt;beta&gt; &amp; more" in render_plain(spec)
    assert "0.5.0 <beta> & more" not in render_plain(spec)
