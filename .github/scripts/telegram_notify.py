#!/usr/bin/env python3
"""Render and send a CI notification to Telegram.

One notify spec (see docs/superpowers/plans/2026-07-28-pr-merge-gate-and-notifications.md)
is rendered twice: as Bot API 10.1 rich markup for `sendRichMessage`, and — for the fallback —
as the small inline subset `sendMessage` accepts. They are separate renderings on purpose: the
`sendMessage` parser rejects `h1`, `table`, `details`, `ul`, `p` and `footer`.

Emphasis rule: bold marks exactly what needs attention (failed contexts, failing rows, failed
job names, breached Sonar conditions) and nothing else, so "bold = problem" stays unambiguous.

Usage:
    NOTIFY_SPEC_FILE=spec.json python3 telegram_notify.py            # send
    NOTIFY_SPEC_FILE=spec.json python3 telegram_notify.py --dry-run  # print both renderings
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
    """Escape the three characters both Telegram parsers treat as markup."""
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
    """Render segments to inline markup understood by both Telegram parsers."""
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
        body = block.get("html", "")
    link = block.get("link")
    if link:
        body += f'<p><a href="{esc(link["url"])}">{esc(link["text"])}</a></p>'
    return body


def _plain_block_body(block: dict) -> str:
    kind = block.get("type")
    if kind == "table":
        lines = []
        for row in block.get("rows", []):
            cells = [_render_segments(cell) for cell in row]
            lines.append(" — ".join(cells) if len(cells) > 1 else cells[0])
        body = "\n".join(lines)
    elif kind == "list":
        body = "\n".join(f"• {_render_segments(item)}" for item in block.get("items", []))
    else:
        body = esc(block.get("plain", ""))
    link = block.get("link")
    if link:
        body += f'\n<a href="{esc(link["url"])}">{esc(link["text"])}</a>'
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


def render_plain(spec: dict) -> str:
    """Render the spec for the `sendMessage` fallback.

    A separate rendering, not a degraded copy: bold title, verdict line, one
    `<blockquote expandable>` per block, and the links as a text line (the fallback carries no
    inline keyboard, so the URLs have to survive in the text).
    """
    lines = [f"<b>{icon_for(spec.get('status', ''))} {esc(spec.get('title', ''))}</b>"]
    verdict = _render_segments(spec.get("verdict"))
    if verdict:
        lines.append(verdict)
    for block in spec.get("blocks", []):
        lines.append("")
        title = block.get("title")
        if title:
            lines.append(f"<b>{esc(title)}</b>")
        lines.append(f"<blockquote expandable>{_plain_block_body(block)}</blockquote>")
    buttons = spec.get("buttons") or []
    if buttons:
        lines.append("")
        lines.append(" · ".join(f'<a href="{esc(b["url"])}">{esc(b["text"])}</a>' for b in buttons))
    footer = spec.get("footer")
    if footer:
        lines.append(esc(footer))
    return "\n".join(lines)


def _reply_parameters(spec: dict) -> dict:
    """The optional request fields shared by both methods (reply target and buttons)."""
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


def build_plain_payload(spec: dict, chat_id: str) -> dict:
    """Build the `sendMessage` fallback body (no inline keyboard — links live in the text)."""
    payload: dict = {
        "chat_id": chat_id,
        "text": render_plain(spec),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if spec.get("silent"):
        payload["disable_notification"] = True
    payload.update(_reply_parameters(spec))
    return payload


def _post(token: str, method: str, payload: dict) -> dict | None:
    """POST a JSON body to one Bot API method. Returns the parsed body, or None on failure."""
    request = urllib.request.Request(  # noqa: S310
        f"{_API_BASE}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "telegram-notify"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310
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
    if not body.get("ok"):
        print(f"{method} rejected: {body.get('description')}", file=sys.stderr)
        return None
    return body


def send(token: str, chat_id: str, spec: dict) -> int | None:
    """Send the notification, falling back to `sendMessage` if the rich send fails.

    `sendRichMessage` is young; the fallback covers an API-side regression, and because the
    fallback is a *different rendering* (not the same HTML) it cannot fail for the same reason.

    Returns:
        The Telegram `message_id`, or ``None`` if both attempts failed.
    """
    body = _post(token, "sendRichMessage", build_rich_payload(spec, chat_id))
    if body is None:
        print("Falling back to sendMessage", file=sys.stderr)
        body = _post(token, "sendMessage", build_plain_payload(spec, chat_id))
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
    parser.add_argument("--dry-run", action="store_true", help="Print both renderings and exit without sending.")
    args = parser.parse_args()

    spec_file = os.environ.get("NOTIFY_SPEC_FILE")
    spec = json.loads(Path(spec_file).read_text()) if spec_file else spec_from_env(dict(os.environ))

    if args.dry_run:
        print("--- rich ---")
        print(render_rich(spec))
        print("--- plain ---")
        print(render_plain(spec))
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
