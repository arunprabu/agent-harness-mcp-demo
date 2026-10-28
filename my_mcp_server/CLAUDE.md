# CLAUDE.md

A demo MCP server and agent clients for students who are **learning AI agents**. They are new to MCP, so keep every file short, flat and easy to read top to bottom.

Work only inside this folder. Do not read or copy from the parent folder or its sibling projects. Never read `.env` files; `.env.example` is fine.

## Rules for code in this project

- Simple beats clever. No classes, base classes, config layers, decorators of our own, or "utils" modules unless the user asks.
- One idea per file. A student should understand a file without opening another.
- Short comments that explain *why* or the MCP concept, written for a beginner.
- `print()` is fine for showing what happens: the server uses Streamable HTTP, so stdout is not the protocol channel.
- The server only uses public APIs that need no API key.
- Don't add tests, auth, databases or a UI unless asked. Docker exists only to deploy the server (`mcp_server/Dockerfile`); don't add more containers unless asked. Verify by running things (see below).

## Layout

Each code folder is its **own uv project** (its own `pyproject.toml`, `uv.lock` and `.venv`). Run `uv` commands from inside the folder.

| Folder | What it is |
|---|---|
| `mcp_server/` | `server.py`: the MCP server, Streamable HTTP at **http://127.0.0.1:9001/mcp**. `Dockerfile` + `.dockerignore`: the server's container image |
| `langchain_client/` | `agent.py`: a LangChain agent (OpenAI) that uses the server's resource, tools and prompt, then chats |
| `langgraph_client/` | `agent.py`: a LangGraph agent (OpenAI). Same five steps as the LangChain client, but builds the agent loop itself: `StateGraph` with an agent node and a `ToolNode`, `tools_condition`, an `InMemorySaver` checkpointer, streamed steps, and `recursion_limit` |
| `guides/` | Student guides, numbered in reading order (listed below) |

The guides, in reading order. New guides take the next number; keep the README's guide table in sync. Guides link to each other as siblings (`02_...md`) and to code as `../mcp_server/...`.

| Guide | What it covers | Update it when |
|---|---|---|
| `01_AUTH_NOTES.md` | The two auth layers, token passthrough, production OAuth, and how LangChain/LangGraph connect to a protected server | the auth design changes |
| `02_MCP_AUTH_IMPLEMENTATION.md` | Step-by-step guide to the server's auth, with test commands; its commands run from `mcp_server/` | the auth code changes |
| `03_OAUTH_GUIDE.md` | Users sign in at a web chat frontend (BFF, auth code + PKCE), one MCP client per user request, a JWT verifier, token exchange to REST APIs, and the MCP spec's own OAuth flow (`OAuthClientProvider`) | the OAuth advice or SDK facts change |
| `04_DEPLOYMENT_GUIDE.md` | Deploy to AWS ECR + ECS Fargate behind an ALB (AWS CLI, bash); its commands run from `mcp_server/` | the port, env vars, `/health` or the Dockerfile change |

Clients talk to the server **only over HTTP**. They never import `server.py`. That separation is the point of MCP, so keep it. Each folder keeps its secrets in its own `.env`, with a `.env.example` beside it.

Keep this layout table, and the tables in `README.md`, in sync when files, tools, resources or prompts change.

## The MCP server (`mcp_server/server.py`)

| Kind | Name | Backed by |
|---|---|---|
| tool | `get_weather(city)` | Open-Meteo geocoding + forecast |
| tool | `get_products(category?, limit=5)` | Fake Store API (`category` is an enum; the API spells it `jewelery`) |
| tool | `get_users()` | JSONPlaceholder `/users`, playing a protected API: sends `USERS_API_TOKEN` as a Bearer token |
| resource | `info://about` | static text |
| prompt | `weather_report(city)` | uses `get_weather` |

Besides MCP, the server answers `GET /health` with `ok` (a `custom_route`, no API key) for the load balancer's health check. `HOST` (default `127.0.0.1`; the Dockerfile sets `0.0.0.0`) and `SERVER_URL` (default `http://127.0.0.1:9001/mcp`) come from the environment.

`.mcp.json` (at the root) registers the server with Claude Code, so Claude Code itself can be the MCP client while the server is running. It sends `Authorization: Bearer ${MCP_API_KEY}`, so start Claude Code with that variable set.

## Auth: two layers (details in `guides/01_AUTH_NOTES.md`, per-user OAuth in `guides/03_OAUTH_GUIDE.md`)

1. **Clients → MCP server.** `MCP_API_KEY` from `mcp_server/.env`, checked by `ApiKeyVerifier` (a `TokenVerifier`) on every request. Missing or wrong → 401. Clients send `Authorization: Bearer <MCP_API_KEY>`.
2. **Tool → protected REST API.** The server's own `USERS_API_TOKEN`, used by `get_users`.

Rules to keep:

- Never forward the client's token to a backend API (token passthrough is forbidden by the MCP spec). Tools use the server's own credential, or a token exchange.
- Never take secrets as tool arguments (the model sees them), and never print or return a token.
- Map backend 401/403 to a `ToolError` with a clear message.

## Commands

```bash
cd mcp_server && uv run server.py           # start the server (leave it running). Needs mcp_server/.env from .env.example
cd langchain_client && uv run agent.py      # needs the server running, and OPENAI_API_KEY + MCP_API_KEY in langchain_client/.env
cd langgraph_client && uv run agent.py      # same, with langgraph_client/.env
cd mcp_server && docker build --platform linux/arm64 -t my-mcp-server .   # the image deployed to AWS (guides/04_DEPLOYMENT_GUIDE.md)
docker run --rm -p 9001:9001 -e MCP_API_KEY=test -e USERS_API_TOKEN=test my-mcp-server
npx @modelcontextprotocol/inspector         # MCP Inspector UI (needs Node). Transport: Streamable HTTP, URL above
```

To verify a server change: start the server, then call every tool once (MCP Inspector, or a throwaway client script outside the project). Watch the `[tool] ...` lines in the server terminal. Also check that a request without the key gets a 401. You can pass test keys on the command line instead of creating a `.env`: `MCP_API_KEY=test USERS_API_TOKEN=test uv run server.py` (`load_dotenv` never overrides variables that are already set).

To verify a client change: run it with the server up. Without an OpenAI key it should still print the resource and the tool list before OpenAI stops it.

## MCP Python SDK v2 in the server (checked against `mcp` 2.3.0)

Most examples online are for v1. Check imports against the installed package.

- `FastMCP` was renamed **`MCPServer`**: `from mcp.server.mcpserver import MCPServer`. `mcp.server.fastmcp` no longer exists.
- Decorators are unchanged: `@mcp.tool()`, `@mcp.resource("scheme://path")`, `@mcp.prompt()`.
- `mcp.run(transport="streamable-http", host=..., port=...)` serves at `/mcp`.
- Sync (`def`) tools run in a worker thread, so a blocking `httpx.get` doesn't stall the server.
- Raise `ToolError` (`mcp.server.mcpserver.exceptions`) for errors the model should read. Other exceptions reach the client as a generic "Error executing tool ...".
- Auth: `MCPServer(token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=False))`. Both are required together. `TokenVerifier` and `AccessToken` come from `mcp.server.auth.provider`, `AuthSettings` from `mcp.server.auth.settings`. The SDK returns 401 with `WWW-Authenticate` and serves `/.well-known/oauth-protected-resource/mcp`.
- `get_access_token()` (`mcp.server.auth.middleware.auth_context`) works inside sync tools too: the context reaches the worker thread.
- `@mcp.custom_route(path, methods=[...])` adds a plain Starlette route (handler takes a `Request`, returns a `Response`). Custom routes skip auth.
- `host` 127.0.0.1/localhost/::1 turns on DNS-rebinding protection (only localhost `Host` headers are accepted); `0.0.0.0` leaves it off.
- `validate_token_resource=True` compares `AccessToken.resource` with `resource_server_url`, so the verifier must set `resource`, or every token gets 401.
- `mcp.run(..., stateless_http=True)` drops in-memory sessions, so several replicas can serve one client.

## LangChain client (checked against `langchain` 1.4.7, `langchain-mcp-adapters` 0.3.2)

- Use `langchain-mcp-adapters` (`MultiServerMCPClient`). It covers tools, prompts and resources. `langchain.mcp` also exists, but it is beta, warns on import and only does tools.
- The adapter pulls in `mcp` 1.x for the client while the server runs `mcp` 2.x. That is fine: they only share the protocol over HTTP.
- Connection config: `{"transport": "streamable_http", "url": ..., "headers": {...}}` (underscore, not hyphen). For OAuth, use `"auth": <httpx.Auth>`, e.g. `mcp.client.auth.OAuthClientProvider`. A 401 surfaces as an `ExceptionGroup` wrapping `httpx.HTTPStatusError`.
- `get_tools()`, `get_resources(server, uris=[...])` returns `Blob`s (`.as_string()`), `get_prompt(server, name, arguments=...)` returns LangChain messages.
- A tool that raises `ToolError` comes back to the agent as a `ToolMessage` with `status="error"`; it does not crash the run.
- The model is the `MODEL` constant in `agent.py`, in LangChain's `provider:model` format. Use `message.text` (a property) for the reply text.

## LangGraph client (checked against `langgraph` 1.2.18)

- Imports: `StateGraph, MessagesState, START` from `langgraph.graph`; `ToolNode, tools_condition` from `langgraph.prebuilt`; `InMemorySaver` from `langgraph.checkpoint.memory`; `GraphRecursionError` from `langgraph.errors`. None of them warn about deprecation.
- The default `recursion_limit` is **10007** (env `LANGGRAPH_DEFAULT_RECURSION_LIMIT`), not 25 as in older versions. Always set it in the run config.
- `ToolNode`'s default `handle_tool_errors` only catches argument-validation errors and re-raises everything else. MCP tool errors are fine, because the adapter returns them as `ToolMessage(status="error")` rather than raising.
- Keep the MCP code identical to the LangChain client, so students see that only the agent part changes.
- To test the graph wiring without LLM calls, build it and print `graph.get_graph().draw_mermaid()`.
