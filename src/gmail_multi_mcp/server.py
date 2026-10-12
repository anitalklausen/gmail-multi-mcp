"""MCP server exposing tools over every configured Gmail account."""

from __future__ import annotations

import errno
import functools
import os
from email.utils import formataddr, getaddresses, parseaddr

import httplib2
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from . import accounts
from .gmail import SUMMARY_HEADERS, build_raw, full_message, headers_of, summarize

mcp = MCPServer(
    "gmail-multi",
    instructions=(
        "Access to several Gmail accounts. Call list_accounts first to see which "
        "accounts exist. Every tool takes an `account` (email address or alias); "
        "search_emails searches all accounts when it is omitted. To send from another "
        "of the account's addresses, check list_send_as and pass from_address. Always confirm "
        "with the user before sending email."
    ),
)

GLOBAL_READ_ONLY = os.environ.get("GMAIL_MCP_READ_ONLY", "").lower() in ("1", "true", "yes")


# Errors where the request cannot have reached Google, so even a send is safe to retry.
_NOT_SENT = {errno.EADDRNOTAVAIL, errno.EPIPE, errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH}


def _network_retry(idempotent: bool):
    """Retry once with fresh connections after a network error.

    Read-only tools retry on any network error. Tools that change things
    (send, label, trash) retry only when the request was never delivered, so a
    timed-out send is never sent twice.
    """

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (OSError, httplib2.HttpLib2Error) as e:
                if not idempotent and getattr(e, "errno", None) not in _NOT_SENT:
                    raise
                accounts.reset_connections()
                return fn(*args, **kwargs)

        return wrapper

    return decorate


def _check_writable(account: str) -> None:
    if accounts.is_read_only(account):
        raise ValueError(f"Account '{account}' was added read-only; write actions are disabled.")


def _get(account: str, message_id: str, fmt: str = "full") -> dict:
    kwargs = {"userId": "me", "id": message_id, "format": fmt}
    if fmt == "metadata":
        kwargs["metadataHeaders"] = SUMMARY_HEADERS + ["Message-ID", "References", "Delivered-To"]
    return accounts.service_for(account).users().messages().get(**kwargs).execute()


def _label_ids(account: str, names: list[str]) -> list[str]:
    if not names:
        return []
    labels = accounts.service_for(account).users().labels().list(userId="me").execute()["labels"]
    by_name = {l["name"].lower(): l["id"] for l in labels}
    by_id = {l["id"]: l["id"] for l in labels}
    out = []
    for n in names:
        lid = by_id.get(n) or by_name.get(n.lower())
        if not lid:
            raise ValueError(f"Unknown label '{n}' in {account}")
        out.append(lid)
    return out


# ---------------------------------------------------------------- read tools


@mcp.tool()
def list_accounts() -> list[dict]:
    """List all connected Gmail accounts with their alias and read-only status."""
    return [
        {"email": email, "alias": meta.get("alias"), "read_only": bool(meta.get("read_only")) or GLOBAL_READ_ONLY}
        for email, meta in accounts.load_registry().items()
    ]


@mcp.tool()
@_network_retry(idempotent=True)
def search_emails(query: str = "", account: str | None = None, max_results: int = 10) -> dict:
    """Search email using Gmail search syntax (e.g. 'is:unread from:bob newer_than:7d').

    Args:
        query: Gmail search query. Empty returns the newest messages.
        account: Email or alias. Omit to search ALL connected accounts.
        max_results: Max messages per account (1-50).
    """
    max_results = max(1, min(max_results, 50))
    targets = [account] if account else list(accounts.load_registry())
    results, errors = [], {}
    for acc in targets:
        try:
            email = accounts.resolve(acc)
            svc = accounts.service_for(email)
            resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            for m in resp.get("messages", []):
                results.append(summarize(email, _get(email, m["id"], "metadata")))
        except (HttpError, ValueError) as e:
            errors[acc] = str(e)
    out: dict = {"messages": results}
    if errors:
        out["errors"] = errors
    return out


@mcp.tool()
@_network_retry(idempotent=True)
def read_email(account: str, message_id: str, max_body_chars: int = 20000) -> dict:
    """Read one email in full (headers, plain-text body, attachment list)."""
    email = accounts.resolve(account)
    return full_message(email, _get(email, message_id), max_body_chars)


@mcp.tool()
@_network_retry(idempotent=True)
def read_thread(account: str, thread_id: str, max_body_chars: int = 8000) -> list[dict]:
    """Read every message in a conversation thread, oldest first."""
    email = accounts.resolve(account)
    thread = accounts.service_for(email).users().threads().get(userId="me", id=thread_id, format="full").execute()
    return [full_message(email, m, max_body_chars) for m in thread.get("messages", [])]


@mcp.tool()
@_network_retry(idempotent=True)
def list_labels(account: str) -> list[dict]:
    """List labels (system and user-created) for an account."""
    labels = accounts.service_for(account).users().labels().list(userId="me").execute()["labels"]
    return [{"id": l["id"], "name": l["name"], "type": l.get("type")} for l in labels]


@mcp.tool()
@_network_retry(idempotent=True)
def list_send_as(account: str) -> list[dict]:
    """List the addresses this account can send from (Gmail's "Send mail as"),
    including which one is Gmail's default sender."""
    return [
        {
            "address": s["sendAsEmail"],
            "display_name": s.get("displayName") or None,
            "default": bool(s.get("isDefault")),
            "primary": bool(s.get("isPrimary")),
        }
        for s in _send_as(accounts.resolve(account))
    ]


def _send_as(email: str) -> list[dict]:
    svc = accounts.service_for(email)
    entries = svc.users().settings().sendAs().list(userId="me").execute().get("sendAs", [])
    # Unverified aliases can't be used to send.
    return [s for s in entries if s.get("isPrimary") or s.get("verificationStatus") == "accepted"]


def _sender(email: str, from_address: str | None, reply_headers: dict | None) -> str:
    """Pick the From header: an explicit alias, else the alias the original
    message was sent to (when replying), else Gmail's default sender."""
    entries = _send_as(email)
    by_addr = {s["sendAsEmail"].lower(): s for s in entries}
    chosen = None
    if from_address:
        chosen = by_addr.get(parseaddr(from_address)[1].lower())
        if not chosen:
            options = ", ".join(s["sendAsEmail"] for s in entries)
            raise ValueError(f"'{from_address}' is not a send-as address for {email}. Options: {options}")
    elif reply_headers:
        recipients = ", ".join(reply_headers.get(k, "") for k in ("to", "cc", "delivered-to"))
        for _, addr in getaddresses([recipients]):
            if addr.lower() in by_addr:
                chosen = by_addr[addr.lower()]
                break
    if not chosen:
        chosen = next((s for s in entries if s.get("isDefault")), None) or by_addr.get(email)
    if not chosen:
        return email
    return formataddr((chosen.get("displayName") or "", chosen["sendAsEmail"]))


# ---------------------------------------------------------------- write tools


def _compose(account: str, to: str, subject: str, body: str, cc, bcc, reply_to_message_id, from_address=None):
    email = accounts.resolve(account)
    thread_id = in_reply_to = references = None
    h = None
    if reply_to_message_id:
        orig = _get(email, reply_to_message_id, "metadata")
        h = {k.lower(): v for k, v in headers_of(orig["payload"]).items()}
        thread_id = orig.get("threadId")
        in_reply_to = h.get("message-id")
        references = h.get("references")
        if not subject:
            subject = h.get("subject", "")
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
    sender = _sender(email, from_address, h)
    raw = build_raw(sender, to, subject, body, cc, bcc, in_reply_to, references)
    msg = {"raw": raw}
    if thread_id:
        msg["threadId"] = thread_id
    return email, msg


@_network_retry(idempotent=False)
def send_email(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to_message_id: str | None = None,
    from_address: str | None = None,
) -> dict:
    """Send an email from the given account. Confirm content with the user first.

    Args:
        account: Sender account (email or alias).
        to: Comma-separated recipients.
        subject: Subject. May be empty when replying (uses 'Re: <original>').
        body: Plain-text body.
        reply_to_message_id: Message id to reply to; keeps the thread intact.
        from_address: Send from one of the account's "Send mail as" addresses
            (see list_send_as). Default: when replying, the address the original
            was sent to; otherwise Gmail's default sender.
    """
    _check_writable(account)
    email, msg = _compose(account, to, subject, body, cc, bcc, reply_to_message_id, from_address)
    sent = accounts.service_for(email).users().messages().send(userId="me", body=msg).execute()
    return {"account": email, "id": sent["id"], "thread_id": sent.get("threadId"), "status": "sent"}


@_network_retry(idempotent=False)
def create_draft(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to_message_id: str | None = None,
    from_address: str | None = None,
) -> dict:
    """Save an email as a draft in the given account (not sent).

    Takes the same arguments as send_email, including from_address for
    choosing a "Send mail as" address.
    """
    _check_writable(account)
    email, msg = _compose(account, to, subject, body, cc, bcc, reply_to_message_id, from_address)
    draft = accounts.service_for(email).users().drafts().create(userId="me", body={"message": msg}).execute()
    return {"account": email, "draft_id": draft["id"], "status": "draft saved"}


@_network_retry(idempotent=False)
def modify_labels(
    account: str,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict:
    """Add/remove labels by name or id. Examples: mark read = remove ['UNREAD'];
    archive = remove ['INBOX']; star = add ['STARRED']."""
    _check_writable(account)
    email = accounts.resolve(account)
    body = {"addLabelIds": _label_ids(email, add_labels or []), "removeLabelIds": _label_ids(email, remove_labels or [])}
    res = accounts.service_for(email).users().messages().modify(userId="me", id=message_id, body=body).execute()
    return {"account": email, "id": res["id"], "labels": res.get("labelIds", [])}


@_network_retry(idempotent=False)
def trash_email(account: str, message_id: str) -> dict:
    """Move a message to Trash (recoverable for 30 days)."""
    _check_writable(account)
    email = accounts.resolve(account)
    accounts.service_for(email).users().messages().trash(userId="me", id=message_id).execute()
    return {"account": email, "id": message_id, "status": "trashed"}


if not GLOBAL_READ_ONLY:
    for fn in (send_email, create_draft, modify_labels, trash_email):
        mcp.tool()(fn)


def run() -> None:
    mcp.run()
