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


class TestBuildPayloads:
    def test_rich_payload_shape(self) -> None:
        from ..telegram_notify import build_rich_payload

        payload = build_rich_payload(_spec(reply_to=4711, silent=True), "-100123")
        assert payload["chat_id"] == "-100123"
        assert payload["rich_message"]["skip_entity_detection"] is True
        assert payload["rich_message"]["html"].startswith("<h1>")
        assert payload["disable_notification"] is True
        assert payload["reply_parameters"] == {"message_id": 4711, "allow_sending_without_reply": True}
        assert payload["reply_markup"] == {
            "inline_keyboard": [[{"text": "Pull request", "url": "https://github.com/o/r/pull/118"}]]
        }

    def test_rich_payload_without_reply_or_buttons(self) -> None:
        from ..telegram_notify import build_rich_payload

        payload = build_rich_payload(_spec(reply_to=None, buttons=[]), "-100123")
        assert "reply_parameters" not in payload
        assert "reply_markup" not in payload

    def test_plain_payload_shape(self) -> None:
        from ..telegram_notify import build_plain_payload

        payload = build_plain_payload(_spec(reply_to=4711), "-100123")
        assert payload["parse_mode"] == "HTML"
        assert payload["link_preview_options"] == {"is_disabled": True}
        assert payload["text"].startswith("<b>")
        assert "reply_markup" not in payload  # the fallback carries links in the text instead


class TestSpecFromEnv:
    def test_builds_a_minimal_spec(self) -> None:
        from ..telegram_notify import spec_from_env

        spec = spec_from_env(
            {
                "NOTIFY_STATUS": "started",
                "NOTIFY_TITLE": "Add the quota module",
                "NOTIFY_VERDICT": "PR updated",
                "NOTIFY_FOOTER": "claude-tools · PR 118",
                "NOTIFY_BUTTONS": '[{"text": "Pull request", "url": "https://p"}]',
                "NOTIFY_SILENT": "true",
            }
        )
        assert spec["status"] == "started"
        assert spec["verdict"] == [{"text": "PR updated"}]
        assert spec["blocks"] == []
        assert spec["silent"] is True
        assert spec["reply_to"] is None

    def test_verdict_json_wins_and_carries_segments(self) -> None:
        from ..telegram_notify import spec_from_env

        spec = spec_from_env(
            {
                "NOTIFY_VERDICT": "ignored",
                "NOTIFY_VERDICT_JSON": '[{"text": "New commit "}, {"text": "a1b2c3d", "code": true}]',
            }
        )
        assert spec["verdict"] == [{"text": "New commit "}, {"text": "a1b2c3d", "code": True}]

    def test_reply_to_parses_and_tolerates_junk(self) -> None:
        from ..telegram_notify import spec_from_env

        assert spec_from_env({"NOTIFY_REPLY_TO": "4711"})["reply_to"] == 4711
        assert spec_from_env({"NOTIFY_REPLY_TO": ""})["reply_to"] is None
        assert spec_from_env({"NOTIFY_REPLY_TO": "none"})["reply_to"] is None


class TestSend:
    def _install(self, monkeypatch: pytest.MonkeyPatch, responses: list) -> list[dict]:
        import json as json_mod

        from .. import telegram_notify as mod

        calls: list[dict] = []

        def fake_urlopen(request, timeout: float = 30.0):
            calls.append({"url": request.full_url, "body": json_mod.loads(request.data)})
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result

            class _Response:
                def read(self):
                    return json_mod.dumps(result).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Response()

        monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
        return calls

    def test_rich_success_returns_message_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ..telegram_notify import send

        calls = self._install(monkeypatch, [{"ok": True, "result": {"message_id": 4711}}])
        assert send("TKN", "-100123", _spec()) == 4711
        assert calls[0]["url"].endswith("/sendRichMessage")

    def test_falls_back_to_send_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        from ..telegram_notify import send

        calls = self._install(
            monkeypatch,
            [
                urllib.error.HTTPError("https://api.telegram.org", 400, "Bad Request", hdrs=None, fp=None),
                {"ok": True, "result": {"message_id": 99}},
            ],
        )
        assert send("TKN", "-100123", _spec()) == 99
        assert calls[1]["url"].endswith("/sendMessage")
        assert calls[1]["body"]["parse_mode"] == "HTML"

    def test_both_fail_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        from ..telegram_notify import send

        error = urllib.error.HTTPError("https://api.telegram.org", 500, "Boom", hdrs=None, fp=None)
        self._install(monkeypatch, [error, error])
        assert send("TKN", "-100123", _spec()) is None

    def test_ok_false_triggers_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ..telegram_notify import send

        calls = self._install(
            monkeypatch,
            [{"ok": False, "description": "Unsupported start tag h1"}, {"ok": True, "result": {"message_id": 7}}],
        )
        assert send("TKN", "-100123", _spec()) == 7
        assert len(calls) == 2
