# LangGraph Examples

LangGraph from scratch in seven small steps. Each example builds one graph and saves a picture of it next to the script (`src/<example>.png`).

## Setup

You need [uv](https://docs.astral.sh/uv/). Examples 5–7 also need an OpenAI key, and example 6 a Tavily key (free tier at tavily.com).

```bash
uv sync
cp .env.example .env      # add OPENAI_API_KEY and TAVILY_API_KEY
```

## Run them

Run from this folder, not from `src/`, since each example writes its picture to `src/`:

```bash
uv run src/ex1_hello_world.py
```

| # | File | Topic | LLM? |
|---|---|---|---|
| 1 | `ex1_hello_world.py` | The smallest graph: one node, `MessagesState`, a mock LLM | No |
| 2 | `ex2_greet.py` | A custom state with `TypedDict`, two nodes in sequence | No |
| 3 | `ex3_router.py` | Conditional edges: route a number to an "even" or "odd" node | No |
| 4 | `ex4_loops.py` | A loop: validate, retry until valid, then succeed | No |
| 5 | `ex5_research_clarify_answer.py` | The LLM classifies the query as CLEAR or UNCLEAR, and the graph answers or asks for clarification | Yes |
| 6 | `ex6_tool_node.py` | Tool calling with `ToolNode`: the agent loops until there are no more tool calls. Tools include the Tavily MCP server | Yes |
| 7 | `ex7_hitl.py` | Human-in-the-loop: draft, you approve or comment in the terminal, revise, finalize | Yes |

[`src/tool_calling_explainer.md`](src/tool_calling_explainer.md) explains how tool calling works, for example 6.
