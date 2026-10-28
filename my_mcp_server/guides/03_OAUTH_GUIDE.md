# OAuth: users sign in at the chat frontend

Our demo protects the MCP server with one shared API key. That works for one agent, but every request looks the same: the server sees `demo-agent`, and `get_users` returns the same data whoever is chatting.

In a real chat app, people **sign in**, and tools should act **as that person**. When someone asks *"show my team"*, the Users API's auth middleware should see *that user*, apply *their* permissions, and log *their* name.

This guide follows one user's sign-in from the chat frontend, through the agent and the MCP server, to your REST API.

Read [01_AUTH_NOTES.md](01_AUTH_NOTES.md) first. It explains the two auth layers, and why the MCP server must never forward a token it received ("token passthrough").

> The code here is a sketch, not part of this project. For the sign-in itself, use a well-known OAuth library for your web framework (for example Authlib, or MSAL for Entra ID) rather than writing the protocol by hand.

---

## What changes from our demo

| Part | Demo today | With sign-in at the frontend |
|---|---|---|
| Frontend | the terminal (`input()`) | a web chat UI. The browser keeps only a session cookie |
| Agent → MCP server | one client for everyone, with `MCP_API_KEY` | one client per signed-in user, with **that user's** access token |
| MCP server's `verify_token()` | compares the shared key | validates a JWT from your identity provider |
| Who a tool sees (`get_access_token()`) | `client_id="demo-agent"` | `subject` = the user, `client_id` = the chat app |
| `get_users` → Users API | the server's own `USERS_API_TOKEN` | **token exchange**: a new token for the Users API, for the same user |

The MCP protocol itself doesn't change: the token still travels in the `Authorization: Bearer ...` header, and the tools barely change.

## The big picture

```
              (1) sign in
   Browser ─────────────────────▶ Identity provider
  (chat UI) ◀──────────────────── (Keycloak, Entra ID, Okta, Auth0…)
     │       (2) back, with a one-time code   ▲           ▲
     │                                        │           │
     ▼        (3) code → tokens               │           │
  Chat backend ───────────────────────────────┘           │
  (the agent, our MCP client)                             │
     │                                                    │
     │ (4) Bearer <user's token for the MCP server>       │
     ▼        (5) token exchange                          │
  MCP server ─────────────────────────────────────────────┘
     │
     │ (6) Bearer <user's token for the Users API>
     ▼
  Users REST API  (its auth middleware checks the token and the user's permissions)
```

1. The user clicks **Sign in**. The chat backend sends the browser to the identity provider's login page.
2. The user signs in there, with your company's SSO, MFA and so on. The chat app never sees the password. The identity provider sends the browser back with a one-time **code**.
3. The chat backend swaps the code for tokens. It keeps them on the server, and gives the browser only a session cookie.
4. On each chat turn, the agent connects to the MCP server with **that user's** access token.
5. When a tool needs the Users API, the MCP server asks the identity provider to **exchange** the user's token for a new one, issued for the Users API.
6. The tool calls the Users API with the new token. The API's middleware sees the real user and applies their permissions.

### Three services, three tokens

Every access token is issued **for** one service: its *audience*, the `aud` claim inside the token. Each service accepts only tokens issued for it.

| Token | Issued for | Kept by | Must never reach |
|---|---|---|---|
| Session cookie | the chat backend | the browser | anything else. It's a session ID, not an access token |
| Access token for the MCP server | the MCP server | the chat backend | the browser, the model, the Users API |
| Refresh token | the identity provider | the chat backend, encrypted | anything else |
| Access token for the Users API | the Users API | the MCP server, during one tool call | the chat backend, the model |

---

## Step 1. Sign in at the frontend, finish at the backend

The browser starts the sign-in, but the **backend** completes it and keeps the tokens. This is the *backend for frontend* (BFF) pattern, which the IETF's guidance for browser apps calls the most secure option. The reason: any token that JavaScript can read, a cross-site scripting (XSS) bug can steal. JavaScript can't read an `HttpOnly` cookie at all.

The flow is OAuth's **authorization code flow with PKCE**. Your OAuth library builds the login URL. These are the parts that matter:

| Login URL parameter | Why |
|---|---|
| `response_type=code` | Ask for a one-time code, not a token in the URL. |
| `client_id`, `redirect_uri` | Who is asking, and where to send the browser back. The identity provider only accepts redirect URIs registered in advance. |
| `scope=openid mcp:tools` | What the token may do. `openid` signs the user in; `mcp:tools` (a name you choose) asks for access to the MCP server. |
| `resource=https://mcp.mycompany.com/mcp` | **Which service** the token is for ([RFC 8707](https://datatracker.ietf.org/doc/html/rfc8707)). Not every identity provider supports it: Entra ID, for example, uses the scope instead (`api://mcp-server/mcp.tools`). |
| `code_challenge`, `code_challenge_method=S256` | PKCE: a hash of a secret that only the backend knows. Only the backend that started the login can use the code. |
| `state` | A random value checked on the way back, so an attacker can't slip their own login into your session (CSRF). |

When the browser comes back, the backend swaps the code for tokens:

```python
# GET /callback?code=...&state=...   (after checking that state matches the one we sent)
tokens = httpx.post(TOKEN_URL, data={
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": "https://chat.mycompany.com/callback",
    "code_verifier": login["pkce_verifier"],      # PKCE: the secret behind code_challenge
    "client_id": CHAT_CLIENT_ID,
    "client_secret": CHAT_CLIENT_SECRET,          # a backend can keep a secret; a browser can't
    "resource": "https://mcp.mycompany.com/mcp",  # a token for the MCP server
}).json()

save_tokens(session_id, tokens)  # server side: access_token, refresh_token, expires_in
# The browser gets only:  Set-Cookie: session=<session_id>; HttpOnly; Secure; SameSite=Lax
```

> **Already signing users in to the chat app?** If the token you have was issued for the chat backend, don't send it to the MCP server. The MCP server must reject it, because it wasn't issued for the MCP server. Exchange it for a token for the MCP server, the same way as in [Step 4](#step-4-tools-call-your-rest-api-as-the-user-token-exchange).

## Step 2. The agent connects as the user

Today both agents build **one** MCP client at startup, with `MCP_API_KEY`. With signed-in users, build the client **for each request**, with that user's access token. The config is the same; only the token changes:

```python
async def chat_turn(session_id: str, question: str) -> str:
    access_token = await fresh_access_token(session_id)  # refreshes it if it's about to expire

    client = MultiServerMCPClient({
        "my-mcp-server": {
            "transport": "streamable_http",
            "url": MCP_URL,
            "headers": {"Authorization": f"Bearer {access_token}"},
        }
    })
    tools = await client.get_tools()  # the server could list only the tools this user may use
    agent = create_agent(model=MODEL, tools=tools)
    ...
```

Creating the client only stores the config; `get_tools()` then asks the server for its tool list. The LangGraph agent does the same, and passes the tools to `ToolNode`.

Rules for the agent:

- **The token goes in the HTTP header, and nowhere else.** Not in the system prompt, the messages, a tool argument or the graph state. The model sees all of those, and a LangGraph checkpointer saves the state to storage.
- **Never share a client between users.** A client carries one user's token, so a shared client would make every user act as the same person.
- **Refresh before expiry.** Access tokens usually live 5 to 60 minutes. Use the refresh token to get a new one. If the MCP server still answers `401` (it arrives as an `ExceptionGroup` wrapping `httpx.HTTPStatusError`), refresh once and retry. If refreshing fails, the frontend sends the user to sign in again.
- **LangGraph memory belongs to one user.** The checkpointer finds a conversation by its `thread_id`. Before you resume a thread, check that it belongs to the signed-in user, or one user could read another user's chat.

## Step 3. The MCP server checks the user's token

Only `verify_token()` changes. Instead of comparing a shared key, it validates a **JWT** (a signed token) from your identity provider. A sketch with [PyJWT](https://pyjwt.readthedocs.io/):

```python
import jwt  # PyJWT

ISSUER = "https://login.mycompany.com"
SERVER_URL = "https://mcp.mycompany.com/mcp"
# The identity provider's public keys: see "jwks_uri" in its /.well-known/openid-configuration
jwks = jwt.PyJWKClient(JWKS_URL)


class JwtVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"],  # checks the signature and the expiry
                issuer=ISSUER,                      # issued by OUR identity provider
                audience=SERVER_URL,                # issued for THIS server
            )
        except jwt.InvalidTokenError:
            return None  # → 401
        return AccessToken(
            token=token,
            client_id=claims["azp"],  # the app that asked: our chat backend
            subject=claims["sub"],    # the user who signed in
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=SERVER_URL,      # the audience we just checked
        )


mcp = MCPServer(
    "my-mcp-server",
    token_verifier=JwtVerifier(),
    auth=AuthSettings(
        issuer_url=ISSUER,              # published, so OAuth clients know where to sign in
        resource_server_url=SERVER_URL,
        validate_token_resource=True,   # the SDK also refuses tokens whose resource isn't SERVER_URL
        required_scopes=["mcp:tools"],  # every request needs this scope, or the SDK answers 403
    ),
)
```

Two things to watch:

- **`validate_token_resource=True` needs `resource=`.** The SDK compares `AccessToken.resource` with `resource_server_url`. If your verifier leaves `resource` out, every request gets `401`. (The demo uses `False`, because an API key has no audience.)
- **Claim names differ between identity providers.** Entra ID, for example, puts scopes in `scp` instead of `scope`, and its audience is often an ID like `api://mcp-server` rather than a URL. Look at the claims of one real token before you write the verifier.

Inside a tool, `get_access_token()` now tells you **who** is asking. So a tool can apply its own rules:

```python
@mcp.tool()
def get_users() -> list[dict]:
    """Get all users: id, name, email, phone, city and company."""
    caller = get_access_token()
    print(f"[tool] get_users() for user {caller.subject} via {caller.client_id}")
    if "users:read" not in caller.scopes:
        raise ToolError("You don't have permission to read users.")
    ...
```

`required_scopes` applies to the whole server; a check like this one applies to a single tool.

## Step 4. Tools call your REST API as the user (token exchange)

The user's token was issued for the MCP server, so the tool must **not** send it to the Users API: that would be token passthrough. Instead, the MCP server asks the identity provider for a **new** token, issued for the Users API, for the same user. This is OAuth Token Exchange ([RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693)):

```python
def users_api_token(user_token: str) -> str:
    """Swap the user's token (issued for us) for a token for the Users API (same user)."""
    response = httpx.post(TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": user_token,  # on whose behalf
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "audience": "users-api",      # who the new token is for
        "client_id": MCP_CLIENT_ID,          # the MCP server proves who IT is,
        "client_secret": MCP_CLIENT_SECRET,  # with its own credential from the vault
    })
    if response.status_code != 200:
        raise ToolError("Couldn't get access to the Users API for you. Try signing in again.")
    return response.json()["access_token"]


@mcp.tool()
def get_users() -> list[dict]:
    """Get all users: id, name, email, phone, city and company."""
    caller = get_access_token()
    token = users_api_token(caller.token)
    response = httpx.get(USERS_API_URL, headers={"Authorization": f"Bearer {token}"})
    if response.status_code in (401, 403):
        raise ToolError("The Users API refused the request: you may not have access to users.")
    ...
```

**Why this isn't token passthrough:** the user's token goes only to the identity provider, which checks it and decides whether to issue a new one. The Users API only ever sees a token issued for it.

What the Users API's auth middleware gets:

- `aud` is the Users API, so the middleware accepts the token. The token is useless anywhere else.
- `sub` is the same user, so the API applies that user's own permissions and logs their name.
- Some identity providers also add an `act` (actor) claim naming the MCP server, so the logs can say "user X, through the MCP server".

Notes:

- **Entra ID** calls this *On-Behalf-Of*, with different parameters: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, `assertion=<the user's token>`, `requested_token_use=on_behalf_of` and `scope=api://users-api/.default`.
- **Keycloak** calls it *token exchange*. An admin must allow the MCP server's client to use it.
- **Cache** the new token per user until shortly before it expires, so that each tool call doesn't go back to the identity provider.
- If the Users API doesn't need to know who the user is, the server's own credential (what our demo does) is still fine. [01_AUTH_NOTES.md](01_AUTH_NOTES.md) compares the two.

---

## Another case: an MCP server with its own sign-in

Sometimes the MCP server isn't yours. A vendor's MCP server, for example, uses the vendor's identity provider. Then the chat app shows a **Connect** button for it, and the chat backend runs the MCP spec's own [OAuth flow](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization), once per user per server:

1. Call the server without a token. It answers `401`, with a link to its metadata (`resource_metadata`).
2. Read that metadata (`/.well-known/oauth-protected-resource`). It names the server's identity provider.
3. Read the identity provider's metadata, to find its login and token URLs.
4. Identify the chat app to the identity provider: with a pre-registered client ID, a *Client ID Metadata Document* (an HTTPS URL that describes your app), or *Dynamic Client Registration*.
5. Send the user's browser to the login page, with PKCE and `resource=<MCP server URL>`. Swap the returned code for tokens at the backend.
6. Store the tokens for that user and that server. Send them on every request, and refresh them.

Our server already does its part of steps 1 and 2. Call it with `curl -i` and no token to see the `401` ([02_MCP_AUTH_IMPLEMENTATION.md](02_MCP_AUTH_IMPLEMENTATION.md) has the command).

The MCP SDK's `OAuthClientProvider` (`from mcp.client.auth import OAuthClientProvider`) does steps 1 to 6 for you. It's an `httpx.Auth`, so you pass it as `"auth"` in the client config, instead of `headers`. You supply:

- `storage`: a `TokenStorage` with `get_tokens`, `set_tokens`, `get_client_info` and `set_client_info`. In a web app, store these per user in your database.
- `redirect_handler(url)`: called with the login URL. Send that URL to the user's browser.
- `callback_handler()`: waits for the user to come back, then returns the `code` and `state`.

`OAuthClientProvider` suits apps where one process waits for the login, like a desktop app or a CLI. In a web backend, the redirect and the callback are separate HTTP requests, which may even reach different servers. So many teams do steps 5 and 6 with their web framework's OAuth library, and pass the token in `headers` as in Step 2.

---

## Checklist

- Tokens live on the backend. The browser gets only an `HttpOnly`, `Secure` session cookie.
- Sign-in uses the authorization code flow with PKCE and `state`, and an exact, registered redirect URI.
- The MCP server accepts only tokens issued for it: it checks the signature, expiry, issuer and audience.
- The agent sends the user's token only in the `Authorization` header: never in prompts, messages, tool arguments or graph state.
- One MCP client per user request, never shared between users.
- Tools call REST APIs with a token issued for that API: from token exchange, or the server's own credential. Never the user's token for the MCP server.
- Scopes are as small as the job needs: `mcp:tools` for the server, `users:read` for one tool.
- Tokens are refreshed before they expire, and a failed refresh sends the user to sign in again.
- Logs show who called which tool (`caller.subject`), never a token.
- HTTPS everywhere.
