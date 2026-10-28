# AI Agent Harness and Enterprise MCP Server

Course material for building AI agents with LangChain and LangGraph, wrapping them in a harness, and connecting them to a protected MCP server. The slides are in [`AI Agent Harness and Enterprise MCP Server.pdf`](AI%20Agent%20Harness%20and%20Enterprise%20MCP%20Server.pdf).

## Projects

| Project | What it covers | Start here |
|---|---|---|
| [`langchain_examples/`](langchain_examples/) | A first LangChain agent: `create_agent()` with tools loaded from an MCP server | `weather_agent.py` |
| [`langgraph_examples/`](langgraph_examples/) | LangGraph from scratch in 7 steps: state, nodes, routing, loops, tool calling, human-in-the-loop | `src/ex1_hello_world.py` |
| [`harness-demos/`](harness-demos/) | One harness concept per script (context, lifecycle, tools, retries, guardrails, tracing), then all of them combined | [README](harness-demos/README.md) |
| [`my_mcp_server/`](my_mcp_server/) | An MCP server protected by an API key, LangChain and LangGraph clients for it, and guides on auth, OAuth and AWS deployment | [README](my_mcp_server/README.md) |

A suggested order: `langchain_examples` → `langgraph_examples` → `harness-demos` → `my_mcp_server`.

```
.
├── AI Agent Harness and Enterprise MCP Server.pdf   the slides
├── langchain_examples/
├── langgraph_examples/
│   └── src/                ex1 … ex7, each with a .png of its graph
├── harness-demos/
│   └── src/                00 … 08, plus common.py (shared tools)
└── my_mcp_server/
    ├── mcp_server/         the MCP server (also a Dockerfile for AWS)
    ├── langchain_client/   a LangChain agent that uses the server
    ├── langgraph_client/   a LangGraph agent that uses the server
    └── guides/             01 auth notes … 04 deployment guide
```

Each project, and each folder inside `my_mcp_server/`, is its own [uv](https://docs.astral.sh/uv/) project with its own `pyproject.toml` and `uv.lock`.

## Setup

You need [uv](https://docs.astral.sh/uv/) and an OpenAI API key.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                                     # macOS / Linux
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows
```

In each project folder you want to run:

```bash
cp .env.example .env      # then fill in your keys
uv sync                   # creates .venv and installs the exact versions in uv.lock
```

uv downloads the pinned Python version (`.python-version`) if it isn't on the machine, and `uv run` uses the virtualenv without activating it.

**`.env` files are never committed.** Only the `.env.example` templates are in the repo. Each one lists the keys to fill in.

| Key | Used by |
|---|---|
| `OPENAI_API_KEY` | All projects |
| `TAVILY_API_KEY` | `langgraph_examples` (ex6), `harness-demos` (optional) |
| `MCP_API_KEY` | `my_mcp_server` (server and both clients; the values must match) |
| `USERS_API_TOKEN` | `my_mcp_server/mcp_server` |
| `LANGSMITH_*` | Optional tracing in `langgraph_examples` and `harness-demos` |

## Running each project

### langchain_examples

```bash
cd langchain_examples
uv run weather_agent.py
```

It loads its tools from an MCP server at `http://127.0.0.1:8100/mcp`, so start one there first. (The server in `my_mcp_server` listens on port 9001.)

### langgraph_examples

Run from the `langgraph_examples` folder, since each example writes its graph picture to `src/`:

```bash
cd langgraph_examples
uv run src/ex1_hello_world.py
```

| # | File | Topic |
|---|---|---|
| 1 | `ex1_hello_world.py` | The smallest graph: one node, `MessagesState`, a mock LLM |
| 2 | `ex2_greet.py` | A custom state with `TypedDict`, two nodes in sequence |
| 3 | `ex3_router.py` | Conditional edges: route to an "even" or "odd" node |
| 4 | `ex4_loops.py` | A loop: validate, retry, succeed |
| 5 | `ex5_research_clarify_answer.py` | A real LLM decides whether to answer or ask a clarifying question |
| 6 | `ex6_tool_node.py` | Tool calling with `ToolNode`, including tools from the Tavily MCP server (see `src/tool_calling_explainer.md`) |
| 7 | `ex7_hitl.py` | Human-in-the-loop: draft, review, revise, finalize |

### harness-demos

```bash
cd harness-demos/src
uv run 00_plain_agent.py      # then 01 … 08 in order
```

See [harness-demos/README.md](harness-demos/README.md) for what each demo shows, a ~3-hour teaching flow, and exercises.

### my_mcp_server

Start the server in one terminal, then run a client in another:

```bash
cd my_mcp_server/mcp_server && uv run server.py           # http://127.0.0.1:9001/mcp
cd my_mcp_server/langchain_client && uv run agent.py      # or langgraph_client
```

See [my_mcp_server/README.md](my_mcp_server/README.md) for the tools, resources and prompts, trying the server with MCP Inspector or Claude Code, and the guides in reading order.
