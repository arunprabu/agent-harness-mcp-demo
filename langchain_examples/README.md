# LangChain Examples

A first LangChain agent. `weather_agent.py` builds an agent with `create_agent()`, loads its tools from the MCP server in [`../my_mcp_server`](../my_mcp_server/), and asks for the weather in London. It prints the answer and the token usage.

## Setup

You need [uv](https://docs.astral.sh/uv/) and an OpenAI key.

```bash
uv sync
cp .env.example .env      # add your OPENAI_API_KEY; MCP_API_KEY must match ../my_mcp_server/mcp_server/.env
```

## Run it

Start the MCP server in one terminal:

```bash
cd ../my_mcp_server/mcp_server
cp .env.example .env      # the demo values work as they are
uv run server.py          # listens at http://127.0.0.1:9001/mcp
```

Then, from this folder:

```bash
uv run weather_agent.py
```

The agent sends `Authorization: Bearer <MCP_API_KEY>` to the server. Without it, the server answers `401 Unauthorized`.

## Things to try

- Change the question to a made-up city. The system prompt tells the agent to answer "Invalid or Fictional City" instead of calling the tool.
- Ask for products or users: the agent gets every tool the server offers, not only `get_weather`.
- The commented-out `get_weather` at the top is the same tool written locally with `@tool`. Compare it with the MCP version in `../my_mcp_server/mcp_server/server.py`.
