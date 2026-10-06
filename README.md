# gmail-multi-mcp

An open-source [MCP](https://modelcontextprotocol.io) server that connects **any number of Gmail accounts** to Claude (or any MCP client) in one place. Everything runs locally, and your tokens never leave your machine.

## Tools

| Tool | What it does |
|---|---|
| `list_accounts` | Lists the connected accounts, with alias and read-only status |
| `search_emails` | Runs a Gmail search query on **one account or all of them at once** |
| `read_email` / `read_thread` | Reads one message or a whole conversation as plain text, with a list of attachments |
| `list_labels` | Lists the labels for an account |
| `send_email` | Sends mail from a chosen account, including threaded replies |
| `create_draft` | Saves a draft instead of sending |
| `modify_labels` | Marks mail read or unread, archives, stars, or adds and removes labels |
| `trash_email` | Moves a message to Trash (recoverable) |

Every tool takes an `account` argument, which can be the full email address or an alias such as `work`.

## 1. Create a Google OAuth client (once)

1. Open <https://console.cloud.google.com/> and create a project.
2. **APIs & Services → Library** → enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose *External* and fill in the app name and your email. Under **Test users**, add every Gmail address you want to connect.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → *Desktop app*. Download the JSON file.
5. Save the file as `~/.config/gmail-multi-mcp/credentials.json`.

> **Tip:** while the app is in *Testing* status, Google expires refresh tokens after 7 days. For personal use you can click **Publish app** on the consent screen. It stays unverified, so you'll see an "unverified app" warning when you sign in, but the tokens stop expiring.

One OAuth client works for all your accounts.

## 2. Install

Install [uv](https://docs.astral.sh/uv/). It also installs Python for you:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install the server straight from GitHub:

```bash
uv tool install https://github.com/anitalklausen/gmail-multi-mcp/archive/refs/heads/main.zip
```

To install from a local clone instead, run `uv tool install .` in the project folder.

This puts `gmail-multi-mcp` in `~/.local/bin`.

## 3. Connect accounts

Run this once per account. A browser opens where you choose the Google account:

```bash
gmail-multi-mcp add --alias private
gmail-multi-mcp add --alias work
gmail-multi-mcp add --alias shop --read-only
gmail-multi-mcp list
```

Remove an account with `gmail-multi-mcp remove work`. New accounts are picked up by the running server without a restart.

## 4. Add it to Claude

**Claude Desktop:** go to *Settings → Developer → Edit Config* and add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/Users/YOUR_USERNAME/.local/bin/gmail-multi-mcp"
    }
  }
}
```

Use the absolute path, because Claude Desktop does not read your shell's `PATH`. Restart Claude Desktop afterwards.

**Claude Code:**

```bash
claude mcp add gmail --scope user -- ~/.local/bin/gmail-multi-mcp
```

## Configuration

| Environment variable | Effect |
|---|---|
| `GMAIL_MCP_HOME` | Config/token folder. The default is `~/.config/gmail-multi-mcp`. |
| `GMAIL_MCP_CREDENTIALS` | Path to the OAuth client JSON |
| `GMAIL_MCP_READ_ONLY=1` | Hides every write tool (send, draft, labels, trash) for all accounts |

## Security

- Tokens are stored in `tokens/<email>.json` with `600` permissions. Treat them like passwords.
- The default scope is `gmail.modify`: read, send, and change labels, but never permanent deletion. Accounts added with `--read-only` get `gmail.readonly`.
- The server tells the model to confirm with you before sending, and Claude also asks for approval on every tool call.

See also the [privacy policy](PRIVACY.md).

## License

MIT
