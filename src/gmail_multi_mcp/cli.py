"""Command line: manage accounts, or run the MCP server (default)."""

from __future__ import annotations

import argparse
import sys

from . import accounts


def main() -> None:
    parser = argparse.ArgumentParser(prog="gmail-multi-mcp", description="Multi-account Gmail MCP server")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("serve", help="Run the MCP server over stdio (default)")

    add = sub.add_parser("add", help="Connect a Gmail account (opens browser)")
    add.add_argument("--alias", help="Short name, e.g. 'work' or 'private'")
    add.add_argument("--read-only", action="store_true", help="Request read-only access")

    sub.add_parser("list", help="List connected accounts")

    rm = sub.add_parser("remove", help="Disconnect an account")
    rm.add_argument("account", help="Email or alias")

    sub.add_parser("where", help="Print the config directory")

    args = parser.parse_args()

    if args.cmd in (None, "serve"):
        from .server import run

        run()
    elif args.cmd == "add":
        email = accounts.add_account(alias=args.alias, read_only=args.read_only)
        print(f"Connected {email}" + (f" as '{args.alias}'" if args.alias else ""))
        print("The account is available to the running server right away.")
    elif args.cmd == "list":
        reg = accounts.load_registry()
        if not reg:
            print("No accounts yet. Run: gmail-multi-mcp add")
        for email, meta in reg.items():
            flags = [f"alias={meta['alias']}"] if meta.get("alias") else []
            if meta.get("read_only"):
                flags.append("read-only")
            print(email + (f"  [{', '.join(flags)}]" if flags else ""))
    elif args.cmd == "remove":
        try:
            print(f"Removed {accounts.remove_account(args.account)}")
        except ValueError as e:
            sys.exit(str(e))
    elif args.cmd == "where":
        print(accounts.home())


if __name__ == "__main__":
    main()
