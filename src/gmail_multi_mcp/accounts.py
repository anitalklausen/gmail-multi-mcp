"""Account storage and OAuth for multiple Gmail accounts.

Layout of the config directory (default ~/.config/gmail-multi-mcp, override
with GMAIL_MCP_HOME):

    credentials.json          OAuth client (Desktop app) from Google Cloud
    accounts.json             {"<email>": {"alias": "work"}, ...}
    tokens/<email>.json       per-account refresh/access token (chmod 600)
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES_FULL = ["https://www.googleapis.com/auth/gmail.modify"]
SCOPES_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]


def home() -> Path:
    path = Path(os.environ.get("GMAIL_MCP_HOME", Path.home() / ".config" / "gmail-multi-mcp"))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def credentials_file() -> Path:
    return Path(os.environ.get("GMAIL_MCP_CREDENTIALS", home() / "credentials.json"))


def _tokens_dir() -> Path:
    path = home() / "tokens"
    path.mkdir(exist_ok=True, mode=0o700)
    return path


def _token_file(email: str) -> Path:
    return _tokens_dir() / f"{email.lower()}.json"


def _registry_file() -> Path:
    return home() / "accounts.json"


def _write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)


def load_registry() -> dict[str, dict]:
    path = _registry_file()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_registry(registry: dict[str, dict]) -> None:
    _write_private(_registry_file(), json.dumps(registry, indent=2))


def add_account(alias: str | None = None, read_only: bool = False) -> str:
    """Run the browser OAuth flow and store the token. Returns the account email."""
    creds_path = credentials_file()
    if not creds_path.exists():
        raise SystemExit(
            f"Missing OAuth client file: {creds_path}\n"
            "Download it from Google Cloud Console (APIs & Services > Credentials > "
            "OAuth client ID > Desktop app) and save it at that path."
        )
    scopes = SCOPES_READONLY if read_only else SCOPES_FULL
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
    # prompt=select_account lets you pick a different Google account each time.
    creds = flow.run_local_server(
        port=0, prompt="consent select_account", access_type="offline", open_browser=True
    )
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    email = service.users().getProfile(userId="me").execute()["emailAddress"].lower()

    _write_private(_token_file(email), creds.to_json())
    registry = load_registry()
    registry[email] = {"alias": alias, "read_only": read_only}
    _save_registry(registry)
    return email


def remove_account(name: str) -> str:
    email = resolve(name)
    registry = load_registry()
    registry.pop(email, None)
    _save_registry(registry)
    _token_file(email).unlink(missing_ok=True)
    return email


def resolve(name: str) -> str:
    """Map an email address or alias to the stored account email."""
    registry = load_registry()
    key = name.strip().lower()
    if key in registry:
        return key
    for email, meta in registry.items():
        if (meta.get("alias") or "").lower() == key:
            return email
    known = ", ".join(_label(e, m) for e, m in registry.items()) or "none"
    raise ValueError(f"Unknown account '{name}'. Configured accounts: {known}")


def _label(email: str, meta: dict) -> str:
    return f"{email} ({meta['alias']})" if meta.get("alias") else email


_services: dict[str, object] = {}
_lock = threading.Lock()


def service_for(name: str):
    """Return an authorized Gmail API client for the account (cached)."""
    email = resolve(name)
    with _lock:
        if email in _services:
            return _services[email]
        token_path = _token_file(email)
        if not token_path.exists():
            raise ValueError(f"No token for {email}. Run: gmail-multi-mcp add")
        creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds.valid:
            if creds.refresh_token:
                creds.refresh(Request())
                _write_private(token_path, creds.to_json())
            else:
                raise ValueError(f"Token for {email} is invalid. Re-run: gmail-multi-mcp add")
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        _services[email] = svc
        return svc


def is_read_only(name: str) -> bool:
    return bool(load_registry().get(resolve(name), {}).get("read_only"))
