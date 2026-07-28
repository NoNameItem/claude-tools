"""Golden-output tests for telegram_notify.py rendering."""

from __future__ import annotations

import pytest

from ..telegram_notify import esc, icon_for, render_rich

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


def test_html_body_is_trusted_but_text_segments_are_escaped() -> None:
    """`html` block bodies arrive pre-rendered from release_notes._inline and are passed through
    un-escaped (see `_rich_block_body`); every ordinary `text` segment still goes through `esc`,
    so `<`/`>`/`&` in it can't corrupt the surrounding rich markup.
    """
    spec = _spec(
        verdict=[{"text": "Fix <T> & <U>"}],
        blocks=[
            {
                "type": "html",
                "title": "Release notes",
                "html": "<h2>0.5.0 &lt;beta&gt;</h2>",
            }
        ],
    )
    rendered = render_rich(spec)
    assert "<h2>0.5.0 &lt;beta&gt;</h2>" in rendered
    assert "<p>Fix &lt;T&gt; &amp; &lt;U&gt;</p>" in rendered


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

    def test_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error

        from ..telegram_notify import send

        error = urllib.error.HTTPError("https://api.telegram.org", 500, "Boom", hdrs=None, fp=None)
        calls = self._install(monkeypatch, [error])
        assert send("TKN", "-100123", _spec()) is None
        assert len(calls) == 1

    def test_ok_false_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ..telegram_notify import send

        calls = self._install(monkeypatch, [{"ok": False, "description": "Unsupported start tag h1"}])
        assert send("TKN", "-100123", _spec()) is None
        assert len(calls) == 1

    def test_non_dict_4xx_body_returns_none_instead_of_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 4xx body that parses to valid JSON but isn't a dict (e.g. Telegram fronted by a
        proxy that returns a bare `true` or a list) must not raise `AttributeError` out of
        `_post` — it must degrade to a clean "failed" result (`None`) instead.
        """
        import io
        import urllib.error

        from ..telegram_notify import send

        error = urllib.error.HTTPError(
            "https://api.telegram.org", 400, "Bad Request", hdrs=None, fp=io.BytesIO(b"true")
        )
        calls = self._install(monkeypatch, [error])
        assert send("TKN", "-100123", _spec()) is None
        assert len(calls) == 1
