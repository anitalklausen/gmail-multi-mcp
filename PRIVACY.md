# Privacy Policy: gmail-multi-mcp

_Last updated: 6 October 2026_

gmail-multi-mcp is an open-source program that you run on your own computer. It connects your Gmail accounts to an AI assistant (an MCP client such as Claude Desktop) that you also run.

## What data the app accesses

When you connect a Gmail account, the app asks Google for permission to read, send, and organize email in that account (`gmail.modify`). An account added in read-only mode gets read access only (`gmail.readonly`).

## How data is used

- Email data is fetched only when your MCP client calls one of the app's tools, such as search, read, or send.
- That data goes straight from Google to the MCP client on your computer. The app's authors do not run any server, and no email data is ever sent to them.
- Access tokens are stored only on your computer, in `~/.config/gmail-multi-mcp/tokens/`, and only your user account can read them.
- The app does not sell or share data, does not use it for advertising, and does not use it to train AI models.

The app's use of information received from Google APIs follows the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

Your MCP client (for example Claude) handles the email content it receives under its own privacy policy.

## Removing access

- Run `gmail-multi-mcp remove <account>` to delete the stored token for an account.
- To revoke the app's access entirely, go to <https://myaccount.google.com/permissions>.

## Contact

Open an issue in this repository.
