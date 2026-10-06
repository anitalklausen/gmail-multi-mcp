"""Thin helpers around the Gmail API: parsing messages and building MIME."""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from html.parser import HTMLParser

SUMMARY_HEADERS = ["From", "To", "Cc", "Subject", "Date"]


def _b64decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def headers_of(payload: dict) -> dict[str, str]:
    return {h["name"]: h["value"] for h in payload.get("headers", [])}


def _walk(part: dict):
    yield part
    for sub in part.get("parts", []) or []:
        yield from _walk(sub)


def extract_body(payload: dict) -> str:
    plain, html = None, None
    for part in _walk(payload):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if not data or part.get("filename"):
            continue
        if mime == "text/plain" and plain is None:
            plain = _b64decode(data)
        elif mime == "text/html" and html is None:
            html = _b64decode(data)
    if plain:
        return plain.strip()
    if html:
        return html_to_text(html)
    return ""


def attachments_of(payload: dict) -> list[dict]:
    return [
        {
            "filename": p["filename"],
            "mime_type": p.get("mimeType"),
            "size": p.get("body", {}).get("size"),
            "attachment_id": p.get("body", {}).get("attachmentId"),
        }
        for p in _walk(payload)
        if p.get("filename")
    ]


def summarize(account: str, msg: dict) -> dict:
    h = headers_of(msg.get("payload", {}))
    return {
        "account": account,
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        **{k.lower(): h.get(k) for k in SUMMARY_HEADERS if h.get(k)},
        "snippet": msg.get("snippet"),
        "labels": msg.get("labelIds", []),
    }


def full_message(account: str, msg: dict, max_body_chars: int) -> dict:
    payload = msg.get("payload", {})
    body = extract_body(payload)
    truncated = len(body) > max_body_chars
    return {
        **summarize(account, msg),
        "body": body[:max_body_chars] + ("\n…[truncated]" if truncated else ""),
        "attachments": attachments_of(payload),
    }


def build_raw(
    sender: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
