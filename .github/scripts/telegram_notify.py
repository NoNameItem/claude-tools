#!/usr/bin/env python3
"""Render and send a CI notification to Telegram.

One notify spec (see docs/superpowers/plans/2026-07-28-pr-merge-gate-and-notifications.md)
is rendered as Bot API 10.1 rich markup for `sendRichMessage`. There is a single rendering path:
notifications are not critical enough to justify a second, duplicated rendering as insurance
against `sendRichMessage` failing — if the send fails, `main()` returns 1 and the workflow step
goes red, which is the intended failure mode.

Emphasis rule: bold marks exactly what needs attention (failed contexts, failing rows, failed
job names, breached Sonar conditions) and nothing else, so "bold = problem" stays unambiguous.

Usage:
    NOTIFY_SPEC_FILE=spec.json python3 telegram_notify.py            # send
    NOTIFY_SPEC_FILE=spec.json python3 telegram_notify.py --dry-run  # print the rendering
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_API_BASE = "https://api.telegram.org"
_REQUEST_TIMEOUT = 30.0

_ICONS = {
    "started": "🚀",
    "ready": "✅",
    "success": "✅",
    "comments": "⚠️",
    "failed": "❌",
    "failure": "❌",
    "cancelled": "⛔",
    "released": "📦",
}


def esc(text: str) -> str:
    """Escape the three characters Telegram's rich-markup parser treats as markup."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def icon_for(status: str) -> str:
    """Status emoji. The emoji carries the state; the verdict line stays plain text."""
    return _ICONS.get(status, "❓")


def _segments(value) -> list:
    """Normalise a cell/item/verdict into a list of segment dicts."""
    if value is None:
        return []
    if isinstance(value, str | dict):
        value = [value]
    return [{"text": s} if isinstance(s, str) else s for s in value]


def _render_segments(value) -> str:
    """Render segments to the inline markup Telegram's rich-markup parser understands."""
    out = []
    for segment in _segments(value):
        text = esc(segment.get("text", ""))
        if segment.get("code"):
            text = f"<code>{text}</code>"
        if segment.get("href"):
            text = f'<a href="{esc(segment["href"])}">{text}</a>'
        if segment.get("bold"):
            text = f"<b>{text}</b>"
        out.append(text)
    return "".join(out)


def _cell(cell) -> str:
    """One table cell. `align` is a cell property — the icon column is centred."""
    align = cell.get("align") if isinstance(cell, dict) else None
    attr = f' align="{esc(align)}"' if align else ""
    return f"<td{attr}>{_render_segments(cell)}</td>"


def _rich_block_body(block: dict) -> str:
    kind = block.get("type")
    if kind == "table":
        rows = "".join("<tr>" + "".join(_cell(cell) for cell in row) + "</tr>" for row in block.get("rows", []))
        body = f"<table bordered>{rows}</table>"
    elif kind == "list":
        items = "".join(f"<li>{_render_segments(item)}</li>" for item in block.get("items", []))
        body = f"<ul>{items}</ul>"
    else:
        # `html` blocks are pre-rendered rich markup (release_notes.py) — trusted, not escaped.
        # The block carries only an `html` body — there is no separate `plain` body anymore.
        body = block.get("html", "")
    link = block.get("link")
    if link:
        body += f'<p><a href="{esc(link["url"])}">{esc(link["text"])}</a></p>'
    return body


def render_rich(spec: dict) -> str:
    """Render the spec as Bot API 10.1 rich markup for `InputRichMessage.html`.

    Layout (validated against the iOS and desktop clients): `h1` heading — the only level iOS
    renders as a real heading — then the verdict paragraph, then tables and collapsible blocks,
    then the footer last. A block without a `title` is emitted bare (the open check table on a
    failure); a block with one is wrapped in `<details>`.
    """
    parts = [f"<h1>{icon_for(spec.get('status', ''))} {esc(spec.get('title', ''))}</h1>"]
    verdict = _render_segments(spec.get("verdict"))
    if verdict:
        parts.append(f"<p>{verdict}</p>")
    for block in spec.get("blocks", []):
        body = _rich_block_body(block)
        title = block.get("title")
        if title:
            open_attr = " open" if block.get("open") else ""
            body = f"<details{open_attr}><summary>{esc(title)}</summary>{body}</details>"
        parts.append(body)
    footer = spec.get("footer")
    if footer:
        parts.append(f"<footer>{esc(footer)}</footer>")
    return "".join(parts)


def _reply_parameters(spec: dict) -> dict:
    """The optional request fields for the reply target."""
    extra: dict = {}
    reply_to = spec.get("reply_to")
    if reply_to:
        # `allow_sending_without_reply` keeps the notification alive if the anchor message was
        # deleted — a missing reply target must never swallow a failure report.
        extra["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    return extra


def build_rich_payload(spec: dict, chat_id: str) -> dict:
    """Build the `sendRichMessage` request body.

    `skip_entity_detection` is required: without it Telegram auto-linkifies `PR 118` and SHAs
    as hashtags.
    """
    payload: dict = {
        "chat_id": chat_id,
        "rich_message": {"html": render_rich(spec), "skip_entity_detection": True},
    }
    if spec.get("silent"):
        payload["disable_notification"] = True
    payload.update(_reply_parameters(spec))
    buttons = spec.get("buttons") or []
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": b["text"], "url": b["url"]} for b in buttons]]}
    return payload


def _post(token: str, method: str, payload: dict) -> dict | None:
    """POST a JSON body to one Bot API method. Returns the parsed body, or None on failure."""
    request = urllib.request.Request(  # noqa: S310 - Telegram Bot API URL, not user input
        f"{_API_BASE}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "telegram-notify"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310 - same URL as above
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # The Bot API returns its diagnostics in the body of a 4xx — read it, don't discard it.
        try:
            body = json.loads(exc.read())
        except (ValueError, OSError):
            print(f"{method} failed: {exc}", file=sys.stderr)
            return None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"{method} failed: {exc}", file=sys.stderr)
        return None
    # The Bot API's contract is a JSON object, but a 4xx body is arbitrary until parsed: a
    # malformed or unexpected reply (e.g. a bare `true` or a proxy's plain-text error page that
    # happens to parse as JSON) must degrade to a clean "failed" result, not raise out of here.
    if not isinstance(body, dict):
        print(f"{method} failed: unexpected response body: {body!r}", file=sys.stderr)
        return None
    if not body.get("ok"):
        print(f"{method} rejected: {body.get('description')}", file=sys.stderr)
        return None
    return body


def send(token: str, chat_id: str, spec: dict) -> int | None:
    """Send the notification via `sendRichMessage`.

    There is only one send path: PR/CI status notifications are not critical enough to justify
    a second rendering as insurance against this call failing. When it fails, `main()` returns 1
    and the workflow step goes red — that is the intended and sufficient failure mode.

    Returns:
        The Telegram `message_id`, or ``None`` if the send failed.
    """
    body = _post(token, "sendRichMessage", build_rich_payload(spec, chat_id))
    if body is None:
        return None
    return body.get("result", {}).get("message_id")


def spec_from_env(env: dict) -> dict:
    """Build a block-less spec from flat env vars (the composite action's convenience path)."""
    reply_raw = (env.get("NOTIFY_REPLY_TO") or "").strip()
    # NOTIFY_VERDICT_JSON carries segments (bold, `code`); NOTIFY_VERDICT is the plain-text form.
    verdict_json = (env.get("NOTIFY_VERDICT_JSON") or "").strip()
    if verdict_json:
        verdict_segments = json.loads(verdict_json)
    else:
        verdict_text = env.get("NOTIFY_VERDICT") or ""
        verdict_segments = [{"text": verdict_text}] if verdict_text else []
    return {
        "status": env.get("NOTIFY_STATUS") or "started",
        "title": env.get("NOTIFY_TITLE") or "",
        "verdict": verdict_segments,
        "blocks": [],
        "footer": env.get("NOTIFY_FOOTER") or "",
        "buttons": json.loads(env["NOTIFY_BUTTONS"]) if env.get("NOTIFY_BUTTONS") else [],
        "silent": (env.get("NOTIFY_SILENT") or "").lower() == "true",
        "reply_to": int(reply_raw) if reply_raw.isdigit() else None,
    }


def main() -> int:
    """CLI entrypoint. Returns 0 when a message was sent, 1 otherwise."""
    parser = argparse.ArgumentParser(description="Send a CI notification to Telegram.")
    parser.add_argument("--dry-run", action="store_true", help="Print the rendering and exit without sending.")
    args = parser.parse_args()

    spec_file = os.environ.get("NOTIFY_SPEC_FILE")
    spec = json.loads(Path(spec_file).read_text()) if spec_file else spec_from_env(dict(os.environ))

    if args.dry_run:
        print(render_rich(spec))
        return 0

    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Error: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are required", file=sys.stderr)
        return 1

    message_id = send(token, chat_id, spec)
    if message_id is None:
        return 1

    print(message_id)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as handle:
            handle.write(f"message-id={message_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
