"""
My MCP Server: a small demo for learning how AI agents use MCP.

It offers three TOOLS, one RESOURCE and one PROMPT over Streamable HTTP:

    tools      get_weather     -> Open-Meteo API       current weather for a city
               get_products    -> Fake Store API       products from an online store
               get_users       -> JSONPlaceholder API  a list of users (a PROTECTED API in our story)
    resource   info://about    -> a short description of this server
    prompt     weather_report  -> a ready-made instruction that uses get_weather

    tools     : the AI MODEL decides when to call them
    resources : the APP decides when to read them (read-only data)
    prompts   : the USER picks them (reusable instruction templates)

Security has TWO layers (read ../guides/01_AUTH_NOTES.md for the full story):

    agent ──[1] MCP_API_KEY──▶ this MCP server ──[2] USERS_API_TOKEN──▶ Users REST API

    [1] Who may use this MCP server? Every request must carry the header
        "Authorization: Bearer <MCP_API_KEY>". Without it the server answers 401.
    [2] How does a tool call a protected REST API? With the server's OWN
        credential from .env. We never forward the token the client sent us.

Start the server:
    cp .env.example .env
    uv run server.py

It listens at http://127.0.0.1:9001/mcp
To run it in AWS (Docker, ECR, ECS Fargate), see ../guides/04_DEPLOYMENT_GUIDE.md.
"""

import os
import secrets
from typing import Literal

import httpx
from dotenv import load_dotenv
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import PlainTextResponse

# Secrets live in .env: never in the code, and never in tool arguments,
# because the model (and anything that can trick the model) sees those.
load_dotenv()
MCP_API_KEY = os.environ["MCP_API_KEY"]  # [1] clients must send this to use our server
USERS_API_TOKEN = os.environ["USERS_API_TOKEN"]  # [2] our server's own key for the Users API

# The address clients use to reach this server. In AWS that's the load balancer's
# address, so the deployment sets SERVER_URL (see ../guides/04_DEPLOYMENT_GUIDE.md).
SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:9001/mcp")


# ── Layer 1: protect the MCP server ──────────────────────────────────────
# The SDK reads the "Authorization: Bearer <token>" header on EVERY request
# and calls verify_token(). Return an AccessToken to let the request in,
# or None to reject it with "401 Unauthorized". No tool runs before this check.
#
# Demo: one shared API key. In production the token is a short-lived OAuth
# token (a JWT) from your identity provider (Keycloak, Entra ID, Okta, Auth0),
# and verify_token() checks its signature, expiry and audience (it must be
# issued for THIS server). Only this function changes; the tools stay the same.
class ApiKeyVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        # compare_digest takes the same time whatever the input, so an attacker
        # can't guess the key one character at a time by timing our answers.
        if secrets.compare_digest(token.encode(), MCP_API_KEY.encode()):
            # client_id says WHO is calling. With real OAuth tokens it comes
            # from the token itself, so every agent or user gets its own identity.
            return AccessToken(token=token, client_id="demo-agent", scopes=[])
        return None


# Version 2 of the MCP Python SDK renamed FastMCP to MCPServer. It works the same way.
mcp = MCPServer(
    "my-mcp-server",
    token_verifier=ApiKeyVerifier(),
    auth=AuthSettings(
        # Where a client would log in to get a token. The server publishes it at
        # /.well-known/oauth-protected-resource so OAuth clients can find it.
        # We use a fixed API key instead, so this is only a placeholder.
        issuer_url="https://auth.example.com",
        # This server's own address: the "audience" its tokens must be issued for.
        resource_server_url=SERVER_URL,
        # Our verifier checks the key itself. With a real identity provider, set
        # this to True so the SDK rejects tokens that were issued for another service.
        # Then verify_token() must also return AccessToken(resource=SERVER_URL, ...),
        # or the SDK rejects every token with 401 (../guides/03_OAUTH_GUIDE.md, Step 3).
        validate_token_resource=False,
    ),
)


# ── Tools ────────────────────────────────────────────────────────────────
# @mcp.tool() turns a plain function into an MCP tool:
#   - the function name    becomes the tool name
#   - the docstring        becomes the description the model reads
#   - the type hints       become the input schema (JSON Schema)
#   - the return value     is sent back to the model as JSON
# So write names, docstrings and type hints for the model to read.
#
# We use print() so you can watch the calls in the server's terminal.
# That is safe with Streamable HTTP, where messages travel over HTTP, not stdout.


@mcp.tool()
def get_weather(city: str) -> dict:
    """Get the current weather for a city, for example "Pune" or "London"."""
    print(f"[tool] get_weather(city={city!r})")

    # Step 1: find the city's latitude and longitude.
    # params= builds the query string (?name=Pune&count=1) and escapes it safely.
    geo = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
    ).json()
    if not geo.get("results"):
        # A ToolError's message goes back to the model, so it can tell the user.
        # Any other exception reaches the model only as a vague "Error executing tool".
        raise ToolError(f"City not found: {city}")
    place = geo["results"][0]

    # Step 2: get the current weather at that location.
    weather = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        },
    ).json()
    current = weather["current"]

    # Return only what the model needs, with clear names and units.
    # Smaller answers cost fewer tokens and confuse the model less.
    return {
        "city": place["name"],
        "country": place.get("country", ""),
        "temperature_c": current["temperature_2m"],
        "humidity_percent": current["relative_humidity_2m"],
        "wind_speed_kmh": current["wind_speed_10m"],
    }


@mcp.tool()
def get_products(
    # Literal[...] becomes an "enum" in the schema: the model can only pick one of
    # these values, and anything else is rejected before our code runs.
    # "jewelery" is spelled the way the Fake Store API spells it.
    category: Literal["electronics", "jewelery", "men's clothing", "women's clothing"] | None = None,
    # A default value makes the argument optional for the model.
    limit: int = 5,
) -> list[dict]:
    """Get products from an online store. Optionally filter by category."""
    print(f"[tool] get_products(category={category!r}, limit={limit})")

    url = "https://fakestoreapi.com/products"
    if category:
        url = f"{url}/category/{category}"
    products = httpx.get(url, params={"limit": limit}).json()

    return [
        {
            "id": p["id"],
            "title": p["title"],
            "price_usd": p["price"],
            "category": p["category"],
            "rating": p["rating"]["rate"],
        }
        for p in products
    ]


@mcp.tool()
def get_users() -> list[dict]:
    """Get all users: id, name, email, phone, city and company."""
    # Who is calling? The SDK checked the token before this tool ran, so we can
    # trust it here: use it for audit logs, or to check what this caller may do.
    caller = get_access_token()
    print(f"[tool] get_users() called by {caller.client_id}")

    # ── Layer 2: call a protected REST API ──
    # In our story this is the company's Users API, behind auth middleware that
    # wants a token in the Authorization header. (JSONPlaceholder ignores the
    # header, so the demo still works without a real backend.)
    #
    # We send the SERVER's own token (USERS_API_TOKEN), NOT the token the client
    # sent us. Forwarding the client's token is called "token passthrough", and
    # the MCP spec forbids it. ../guides/01_AUTH_NOTES.md explains why, and what to do
    # when the API needs to know which user is asking.
    response = httpx.get(
        "https://jsonplaceholder.typicode.com/users",
        headers={"Authorization": f"Bearer {USERS_API_TOKEN}"},
    )

    # Turn the API's auth errors into a clear message for the model.
    # Never put the token itself in an error message or a log line.
    if response.status_code in (401, 403):
        raise ToolError("The Users API rejected the server's credentials. Ask an admin to check USERS_API_TOKEN.")
    users = response.json()

    return [
        {
            "id": u["id"],
            "name": u["name"],
            "email": u["email"],
            "phone": u["phone"],
            "city": u["address"]["city"],
            "company": u["company"]["name"],
        }
        for u in users
    ]


# ── Resource ─────────────────────────────────────────────────────────────
# Read-only data with an address (a URI), like a file the app can open.
# The app decides when to read it; the model does not call it.


@mcp.resource("info://about")
def about() -> str:
    """What this server does and which public APIs it uses."""
    return (
        "My MCP Server is a demo server for learning AI agents.\n"
        "- get_weather uses Open-Meteo (https://open-meteo.com)\n"
        "- get_products uses Fake Store API (https://fakestoreapi.com)\n"
        "- get_users uses JSONPlaceholder (https://jsonplaceholder.typicode.com), playing a protected API\n"
        "Clients must send 'Authorization: Bearer <MCP_API_KEY>' to use this server."
    )


# ── Prompt ───────────────────────────────────────────────────────────────
# A reusable instruction template. The user picks it and fills in the
# arguments; the client sends the resulting message to the model.


@mcp.prompt()
def weather_report(city: str) -> str:
    """Write a friendly weather report for a city."""
    return (
        f"Use the get_weather tool to check the weather in {city}. "
        "Then write a short, friendly weather report and suggest what to wear."
    )


# ── Health check ─────────────────────────────────────────────────────────
# Not part of MCP: a plain web address that answers "ok" while the server is up.
# In AWS, the load balancer calls it every few seconds (../guides/04_DEPLOYMENT_GUIDE.md).
# Custom routes skip the API key check, so never return anything secret here.


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    # Streamable HTTP: the server runs on its own and many clients can connect to it.
    # (The other transport, stdio, runs the server as a child process of one client.)
    # HOST 127.0.0.1 accepts connections from this computer only. In a container,
    # the Dockerfile sets HOST=0.0.0.0, so connections from outside it can get in.
    mcp.run(transport="streamable-http", host=os.environ.get("HOST", "127.0.0.1"), port=9001)
