# Auth for MCP servers

Your company's REST APIs sit behind auth middleware. So when an MCP tool calls them, it must send a credential. The MCP server itself must also be protected, or anyone who can reach it can run its tools. That gives **two separate layers**, each with its own credential:

```
                 [1]                                  [2]
 Agent  ── Bearer <token for the MCP server> ──▶  MCP server  ── Bearer <token for the REST API> ──▶  REST API
(client)                                        (checks [1])                                     (auth middleware
                                                                                                   checks [2])
```

- **Layer 1: who may use the MCP server?** The client sends a token. The MCP server checks it.
- **Layer 2: how does a tool call a protected API?** The MCP server sends a *different* token, one meant for that API.

The one rule that ties them together: **never forward the token from layer 1 to layer 2.** That's called *token passthrough*, and the MCP spec forbids it ([details below](#never-forward-the-clients-token-token-passthrough)).

In this project, layer 1 is `MCP_API_KEY` and layer 2 is `USERS_API_TOKEN`, used by the `get_users` tool. Both are in `mcp_server/.env`.

This note explains the *why*. For the step-by-step *how* (code, test commands, troubleshooting), see [02_MCP_AUTH_IMPLEMENTATION.md](02_MCP_AUTH_IMPLEMENTATION.md).

---

## Layer 1: protecting the MCP server

### What the MCP spec says

For HTTP servers like ours, the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) builds on **OAuth 2.1**:

| Role | Who plays it |
|---|---|
| **Authorization server** | Your identity provider (Keycloak, Microsoft Entra ID, Okta, Auth0…). It logs users in and issues tokens. |
| **Resource server** | The MCP server. It accepts or rejects tokens. |
| **Client** | The agent (LangChain, LangGraph, Claude Code, MCP Inspector…). It gets a token and sends it. |

The rules that matter most:

- The client sends `Authorization: Bearer <token>` on **every** HTTP request, never in the URL.
- The server **validates** every token: signature, expiry, and that it was issued *for this server* (the token's audience).
- Invalid or missing token → `401 Unauthorized`. Valid token but not allowed (missing scope) → `403 Forbidden`.
- The server publishes where to get a token at `/.well-known/oauth-protected-resource`, and points to it from the `401` response. The SDK does both for you.
- A **stdio** server doesn't use any of this: it runs as the client's child process and reads credentials from environment variables.

### What our demo does

`mcp_server/server.py` uses the SDK's built-in auth. You give `MCPServer` a `TokenVerifier`, and the SDK calls its `verify_token()` on every request, before any tool runs:

```python
class ApiKeyVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token.encode(), MCP_API_KEY.encode()):
            return AccessToken(token=token, client_id="demo-agent", scopes=[])
        return None   # → the SDK answers 401
```

Try it: start the server and call it without the header. You get:

```
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token", ..., resource_metadata="http://127.0.0.1:9001/.well-known/oauth-protected-resource/mcp"
```

Inside a tool, `get_access_token()` tells you who is calling. `get_users` prints it.

### Going to production

A shared API key is fine for a demo or a quick internal tool. For production, use short-lived tokens from your identity provider. **Only `verify_token()` changes**; the tools stay the same. A sketch with [PyJWT](https://pyjwt.readthedocs.io/) (not part of this project):

```python
jwks = jwt.PyJWKClient("https://login.mycompany.com/.well-known/jwks.json")

class JwtVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                issuer="https://login.mycompany.com",
                audience="https://mcp.mycompany.com/mcp",   # issued for THIS server
            )
        except jwt.InvalidTokenError:
            return None
        return AccessToken(
            token=token, client_id=claims["azp"], subject=claims["sub"],
            scopes=claims.get("scope", "").split(), expires_at=claims["exp"],
        )
```

Then set `issuer_url` in `AuthSettings` to your identity provider. To limit what each caller can do, give tools **scopes**: for example, `get_users` checks that `get_access_token().scopes` contains `users:read`.

---

## Layer 2: tools calling your protected REST APIs

Yes: if the REST API has auth middleware, the tool must send a credential that the middleware accepts. The question is **which** credential.

### Never forward the client's token (token passthrough)

It's tempting to take the token the agent sent to the MCP server and pass it on to the REST API. The spec says the MCP server **MUST NOT** do this ([security best practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices#token-passthrough)). Why:

- **Wrong audience.** That token was issued for the MCP server. If the REST API accepts it too, a token stolen from one service works on both.
- **Bypassed controls.** Rate limits and checks that depend on who the caller is no longer line up with who is really calling.
- **Broken audit trail.** The REST API's logs show the user's token, not the MCP server that actually made the call.
- **Confused deputy.** The REST API trusts the request because it came through the MCP server, but the MCP server never checked that the token was meant for it.

### The two right ways

**A. The server's own credential (service account).** This is what our demo does.
The MCP server has its own API key, or gets its own token from the identity provider with the OAuth *client credentials* flow. It keeps that credential in a secret store; we use `.env` in this demo.

```python
response = httpx.get(USERS_API_URL, headers={"Authorization": f"Bearer {USERS_API_TOKEN}"})
```

Use this when the REST API doesn't need to know which end user is asking, or when the MCP server enforces per-user rules itself (using `get_access_token()`).

**B. On behalf of the user (token exchange).**
The MCP server sends the user's token to the identity provider and gets back a **new** token. The new token is issued for the REST API, still names the same user, and usually carries fewer permissions. This is OAuth Token Exchange ([RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693)); Microsoft Entra ID calls it *On-Behalf-Of*.

Use this when the REST API must apply its own per-user permissions, or must log which user did what.

| | A. Service credential | B. Token exchange |
|---|---|---|
| REST API sees | "the MCP server" | "user X, through the MCP server" |
| Per-user permissions enforced by | the MCP server | the REST API |
| Setup | an API key or a client ID and secret | identity provider support for token exchange |

### Rules for tools that call protected APIs

- **Secrets come from the server's environment or a vault, never from tool arguments.** The model sees every argument. A prompt injection could change it, and it ends up in chat history and logs.
- **Never log or return a token.** Not in `print()` calls, and not in error messages.
- **Translate the API's 401 and 403 into a clear `ToolError`**, so the model can tell the user something useful. `get_users` does this.
- **Least privilege.** Give the server's credential only the permissions its tools need, for example read-only.

---

## Connecting LangChain or LangGraph to a protected MCP server

Both use `MultiServerMCPClient` from `langchain-mcp-adapters`. A LangGraph agent loads tools with the same `client.get_tools()` call, so everything below applies to both. There are three ways to send credentials, depending on how the server is protected.

**1. API key or a token you already have: `headers`.** This is what `langchain_client/agent.py` does.

```python
client = MultiServerMCPClient({
    "my-mcp-server": {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:9001/mcp",
        "headers": {"Authorization": f"Bearer {os.environ['MCP_API_KEY']}"},
    }
})
```

**2. A backend agent with no user present: client credentials.** The agent gets its own token from the identity provider, then sends it the same way as in option 1. Request a new token before the old one expires. Parameter names vary by identity provider:

```python
token = httpx.post(TOKEN_URL, data={
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "resource": "https://mcp.mycompany.com/mcp",   # ask for a token for THIS MCP server
}).json()["access_token"]
# then: "headers": {"Authorization": f"Bearer {token}"}
```

**3. A user logs in through the browser: full MCP OAuth with `auth=`.** The connection config also accepts `auth`, which takes any `httpx.Auth`. The MCP SDK's `OAuthClientProvider` (`from mcp.client.auth import OAuthClientProvider`) is one. It reads the server's `401`, finds the identity provider, runs the browser login with PKCE, and refreshes tokens. You provide token storage and the redirect and callback handlers. Use this for desktop or interactive apps.

**Serving many users?** Create the client for each request or session, using that user's token. Never share one client, and its token, across users. [03_OAUTH_GUIDE.md](03_OAUTH_GUIDE.md) walks through the whole flow for a web chat app, from the user's sign-in to your REST API.

**Other clients of this server:**

- **MCP Inspector:** in the connection panel, add the header `Authorization` with the value `Bearer <MCP_API_KEY>`.
- **Claude Code:** `.mcp.json` sends `Authorization: Bearer ${MCP_API_KEY}`, read from your shell. Start Claude Code with `MCP_API_KEY` set.

---

## Production checklist

- HTTPS everywhere. Tokens sent over plain HTTP can be stolen.
- Short-lived tokens from an identity provider, not long-lived shared keys.
- Validate every request. Don't treat an MCP session ID as proof of who the caller is; the spec forbids using sessions for authentication.
- Secrets in a vault or secret manager in production, not `.env` files.
- Least-privilege scopes, for clients (layer 1) and for the server's own credentials (layer 2).
- Log who called which tool (`get_access_token()`), never the token itself.
