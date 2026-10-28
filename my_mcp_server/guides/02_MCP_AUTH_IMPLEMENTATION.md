# MCP Server Auth: Implementation Guide

This guide shows, step by step, how we protected `server.py` with authentication, and how a tool calls a protected REST API. Follow the same steps to protect any MCP server built with the MCP Python SDK.

The files are in `mcp_server/`, so run the commands in this guide from that folder.

For the *why* (the spec, token passthrough, OAuth in production, how clients connect), read [01_AUTH_NOTES.md](01_AUTH_NOTES.md).

> Checked against `mcp` 2.3.0, the MCP Python SDK. In SDK v2, `FastMCP` is called `MCPServer`.

---

## What you will build

```
agent ──[1] Bearer MCP_API_KEY──▶ MCP server ──[2] Bearer USERS_API_TOKEN──▶ Users REST API
```

| Layer | Question it answers | Credential | Checked by |
|---|---|---|---|
| **1** | Who may use this MCP server? | `MCP_API_KEY`, sent by the client | the MCP server, on every request |
| **2** | How does a tool call a protected API? | `USERS_API_TOKEN`, the server's own | the REST API's auth middleware |

Files you will touch:

| File | Change |
|---|---|
| `.env.example`, `.env` | the two secrets |
| `pyproject.toml` | add `python-dotenv` |
| `server.py` | a token verifier, auth settings on `MCPServer`, and a tool that sends its own token |

## How a request flows once auth is on

```
HTTP request to /mcp
   │
   ▼
BearerAuthBackend ── reads "Authorization: Bearer <token>" and calls YOUR verify_token(token)
   │
   ▼
AuthContextMiddleware ── stores the AccessToken you returned, so tools can read it
   │
   ▼
RequireAuthMiddleware ── no valid token? → 401 Unauthorized (missing required scope? → 403)
   │
   ▼
MCP handler ── initialize, tools/list, tools/call ...
   │
   ▼
your tool ── get_access_token() tells it who is calling
```

The SDK provides every box except `verify_token()`. **You write one function, and the SDK does the rest.**

---

## Step 1: Add the dependency

The auth code ships inside the `mcp` package. You only need `python-dotenv`, to read secrets from `.env`:

```bash
uv add python-dotenv
```

## Step 2: Put the secrets in `.env`

Create `.env.example`. It gets committed and shows which variables are needed, with safe demo values:

```bash
# [1] The key clients must send to use this MCP server:
#     Authorization: Bearer <MCP_API_KEY>
MCP_API_KEY=12345ABCDE

# [2] This server's own credential for the protected Users REST API.
USERS_API_TOKEN=demo-users-api-token
```

Copy it to the real file, and make sure `.env` is never committed:

```bash
cp .env.example .env
grep -qx ".env" ../.gitignore || echo ".env" >> ../.gitignore
```

> **Why not in the code?** Code gets committed and shared. **Why not in tool arguments?** The model sees every argument. A prompt injection could change it, and it ends up in chat history and logs.

## Step 3: Load the secrets at startup

At the top of `server.py`:

```python
import os
from dotenv import load_dotenv

load_dotenv()
MCP_API_KEY = os.environ["MCP_API_KEY"]          # [1] clients must send this to use our server
USERS_API_TOKEN = os.environ["USERS_API_TOKEN"]  # [2] our server's own key for the Users API

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:9001/mcp")
```

`os.environ["..."]` (not `os.getenv`) makes the server **stop at startup** if a secret is missing. That's better than starting unprotected, or failing later in the middle of a tool call.

## Step 4: Write a token verifier

This is the only security logic you write. The SDK calls `verify_token()` with the token from the `Authorization` header:

- return an **`AccessToken`** to let the request in
- return **`None`** to reject it with `401`

```python
import secrets
from mcp.server.auth.provider import AccessToken, TokenVerifier


class ApiKeyVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        # compare_digest takes the same time whatever the input, so an attacker
        # can't guess the key one character at a time by timing our answers.
        if secrets.compare_digest(token.encode(), MCP_API_KEY.encode()):
            return AccessToken(token=token, client_id="demo-agent", scopes=[])
        return None
```

The `AccessToken` fields you'll use most:

| Field | Meaning | In our demo |
|---|---|---|
| `client_id` | which app or agent is calling | always `"demo-agent"`, because everyone shares one key |
| `scopes` | what the caller is allowed to do | empty |
| `subject` | which user, for user-based tokens | not set |
| `expires_at` | when the token stops working | not set: an API key doesn't expire |

> Use `secrets.compare_digest`, not `==`. A plain `==` stops at the first wrong character, and that timing difference can leak the key.

## Step 5: Turn on auth in `MCPServer`

Give the server the verifier **and** an `AuthSettings`. The SDK requires both together.

```python
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    "my-mcp-server",
    token_verifier=ApiKeyVerifier(),
    auth=AuthSettings(
        issuer_url="https://auth.example.com",
        resource_server_url=SERVER_URL,
        validate_token_resource=False,
    ),
)
```

| Setting | What it does | Demo value | Production value |
|---|---|---|---|
| `issuer_url` | Where clients log in to get a token. Published at `/.well-known/oauth-protected-resource/mcp` | a placeholder; we use an API key, not OAuth | your identity provider, e.g. `https://login.mycompany.com` |
| `resource_server_url` | This server's own URL: the "audience" tokens must be issued for | `http://127.0.0.1:9001/mcp` | `https://mcp.mycompany.com/mcp` |
| `validate_token_resource` | Should the SDK reject tokens issued for another service? | `False`: our verifier checks the key itself | `True`, with `verify_token()` returning `AccessToken(resource=SERVER_URL, ...)`; or check the audience in `verify_token()` |
| `required_scopes` | Scopes every token must have. Missing → `403 insufficient_scope` | not set | e.g. `["mcp:access"]` |

That's all it takes to protect the server. **Every** request to `/mcp` now goes through `verify_token()`, before any tool, resource or prompt runs.

## Step 6: Know who is calling, inside a tool

The verified `AccessToken` is available in every tool. It works in plain `def` tools as well as `async def` ones.

```python
from mcp.server.auth.middleware.auth_context import get_access_token


@mcp.tool()
def get_users() -> list[dict]:
    """Get all users: id, name, email, phone, city and company."""
    caller = get_access_token()
    print(f"[tool] get_users() called by {caller.client_id}")
    ...
```

Use it for:

- **Audit logs**: who called which tool. Log the `client_id` or `subject`, **never the token**.
- **Per-tool permissions**: for example, only callers with the `users:read` scope may use `get_users`:

```python
if "users:read" not in caller.scopes:
    raise ToolError("You are not allowed to read users.")
```

## Step 7: Call a protected REST API from a tool (layer 2)

Your REST API has auth middleware, so the tool must send a credential. Send the **server's own** token, never the client's:

```python
from mcp.server.mcpserver.exceptions import ToolError


@mcp.tool()
def get_users() -> list[dict]:
    """Get all users: id, name, email, phone, city and company."""
    caller = get_access_token()
    print(f"[tool] get_users() called by {caller.client_id}")

    response = httpx.get(
        "https://jsonplaceholder.typicode.com/users",
        headers={"Authorization": f"Bearer {USERS_API_TOKEN}"},   # the server's own credential
    )

    # Turn the API's auth errors into a clear message for the model.
    # Never put the token itself in an error message or a log line.
    if response.status_code in (401, 403):
        raise ToolError("The Users API rejected the server's credentials. Ask an admin to check USERS_API_TOKEN.")
    users = response.json()
    ...
```

> ❌ **Don't do this:** `headers={"Authorization": f"Bearer {caller.token}"}`
> That forwards the client's token to the API ("token passthrough"), which the MCP spec forbids. That token was issued for the MCP server, not for the Users API. If the API needs to know which **user** is asking, exchange the user's token for a new one issued for the API. See *Token exchange* in [01_AUTH_NOTES.md](01_AUTH_NOTES.md).

In our demo, JSONPlaceholder plays the protected API. It ignores the header, so the demo works without a real backend.

## Step 8: Run and test

Start the server:

```bash
uv run server.py
```

In a second terminal, run these four checks.

**Test 1: no token → 401**

```bash
curl -i -X POST http://127.0.0.1:9001/mcp
```
```
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:9001/.well-known/oauth-protected-resource/mcp"
{"error": "invalid_token", "error_description": "Authentication required"}
```

The `resource_metadata` link is how an OAuth-capable client finds out where to log in.

**Test 2: wrong token → 401**

```bash
curl -i -X POST http://127.0.0.1:9001/mcp -H "Authorization: Bearer wrong-key"
```
```
HTTP/1.1 401 Unauthorized
```

**Test 3: the published auth metadata**

```bash
curl http://127.0.0.1:9001/.well-known/oauth-protected-resource/mcp
```
```json
{"resource":"http://127.0.0.1:9001/mcp","authorization_servers":["https://auth.example.com"],"bearer_methods_supported":["header"]}
```

**Test 4: right token → 200**

```bash
curl -i -X POST http://127.0.0.1:9001/mcp \
  -H "Authorization: Bearer 12345ABCDE" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```
```
HTTP/1.1 200 OK
...
data: {"jsonrpc":"2.0","id":1,"result":{..."serverInfo":{"name":"my-mcp-server","version":""}}}
```

Then call the tools from a real client (Step 9), and watch the server terminal:

```
[tool] get_users() called by demo-agent
```

## Step 9: Connect clients

Every client sends the same header: `Authorization: Bearer <MCP_API_KEY>`.

**LangChain or LangGraph** (`langchain-mcp-adapters`). This is what `../langchain_client/agent.py` does:

```python
client = MultiServerMCPClient({
    "my-mcp-server": {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:9001/mcp",
        "headers": {"Authorization": f"Bearer {os.environ['MCP_API_KEY']}"},
    }
})
```

**MCP Inspector:** add the header `Authorization` with the value `Bearer 12345ABCDE`, then connect.

**Claude Code:** `../.mcp.json` sends `Authorization: Bearer ${MCP_API_KEY}`. Start Claude Code with the variable set:

```bash
MCP_API_KEY=12345ABCDE claude
```

For OAuth-protected servers, LangChain and LangGraph pass `auth=` instead of `headers`. See [01_AUTH_NOTES.md](01_AUTH_NOTES.md).

---

## Going to production

The demo uses one shared, never-expiring key. For production:

1. **Replace `ApiKeyVerifier` with a JWT verifier.** It checks the token's signature against your identity provider's public keys, plus its expiry, issuer and audience. Only `verify_token()` changes. There's a sketch in [01_AUTH_NOTES.md](01_AUTH_NOTES.md).
2. **Point `issuer_url` at your identity provider**, and set `resource_server_url` to the server's public HTTPS URL.
3. **Validate the audience.** Set `validate_token_resource=True` and return `AccessToken(resource=SERVER_URL, ...)` from `verify_token()`, or pass `audience=` to your JWT library. See Step 3 of [03_OAUTH_GUIDE.md](03_OAUTH_GUIDE.md).
4. **Use scopes.** Set `required_scopes` for the whole server, and check `caller.scopes` in sensitive tools.
5. **Run behind HTTPS.** Bearer tokens sent over plain HTTP can be stolen.
6. **Keep secrets in a secret manager** (Vault, AWS Secrets Manager, Azure Key Vault), not `.env` files.
7. **For layer 2**, give the server's own credential the least privilege it needs, or use token exchange when the API must know the user.

## Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| `KeyError: 'MCP_API_KEY'` when starting the server | no `.env`, or the variable is missing | `cp .env.example .env` |
| `ValueError: Cannot specify auth_server_provider or token_verifier without auth settings` | `token_verifier=` without `auth=` | pass both (Step 5) |
| `ValueError: Must specify either auth_server_provider or token_verifier when auth is enabled` | `auth=` without `token_verifier=` | pass both (Step 5) |
| `MCPDeprecationWarning: AuthSettings.validate_token_resource is not set` | `validate_token_resource` left out | set it to `True` or `False` explicitly |
| Every request gets `401` after setting `validate_token_resource=True` | `verify_token()` doesn't set `AccessToken.resource` | return `AccessToken(resource=SERVER_URL, ...)` |
| Every request gets `401` | header missing, misspelled, or without the `Bearer ` prefix; or the client and server keys differ | send exactly `Authorization: Bearer <key>`; compare both `.env` files |
| LangChain client: `ExceptionGroup ... 401 Unauthorized` | same as above, seen from the client | check `MCP_API_KEY` in `langchain_client/.env` |
| `403 insufficient_scope` | the token lacks a scope in `required_scopes` | issue the token with that scope |
| `get_access_token()` returns `None` | auth isn't configured on the server | complete Step 5 |

## Checklist

- [ ] Secrets in `.env`; `.env` in `.gitignore`; `.env.example` committed
- [ ] The server stops at startup if a secret is missing
- [ ] `verify_token()` uses `secrets.compare_digest`, or validates a JWT properly
- [ ] `MCPServer(token_verifier=..., auth=AuthSettings(...))`
- [ ] No token, or a wrong token, gets `401`; the right token gets `200`
- [ ] Tools log `caller.client_id`, never the token
- [ ] Tools call backend APIs with the server's **own** credential (or an exchanged token), never the client's token
- [ ] Backend 401/403 errors become a clear `ToolError`
- [ ] No secret is ever a tool argument
