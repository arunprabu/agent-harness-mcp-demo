# Agent Harness Demos with LangGraph

A step-by-step demo series for fresh engineers. Each script teaches **one** harness concept; the last one combines them all into a small working harness.

> **Agent** = the LLM that *decides* (which tool, which arguments, what to answer).
> **Harness** = the code around it that makes it *safe and reliable* (loop, tools, memory, limits, errors, guardrails, logs).

## Setup (5 minutes)

This project uses [uv](https://docs.astral.sh/uv/). Install it once if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                                     # macOS / Linux
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows
```

Then, from this folder:

```bash
uv sync                    # creates .venv and installs the exact versions in uv.lock
cp .env.example .env       # then put your OPENAI_API_KEY in .env
```

You don't need to activate the virtualenv: `uv run` uses it automatically. uv also downloads the pinned Python (`.python-version`, 3.12) if it isn't on the machine.

**You need an OpenAI key and internet.** The demos run on a real LLM (`openai:gpt-4.1-mini` by default) and get live weather from Open-Meteo, which is free and needs no key. A full run of all demos is a few dozen small LLM calls, which costs a few cents at most.

No key? The demos fall back to a fake rule-based LLM (`offline_llm.py`) with canned answers, so they still run. The weather tool still needs internet.

| Variable | Effect |
|---|---|
| `OPENAI_API_KEY` | **Needed** for the real LLM (default `openai:gpt-4.1-mini`). Without it, the fake offline LLM is used. |
| `MODEL` | Any LangChain `provider:model`, e.g. `anthropic:claude-haiku-4-5`, `google_genai:gemini-2.5-flash` (add the matching package, e.g. `uv add langchain-anthropic`) |
| `TAVILY_API_KEY` | `web_search` uses real Tavily results (free tier at tavily.com) |
| `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` | Bonus: see every run in LangSmith with no code change |

## The demos

| # | File | Topic | What students see |
|---|---|---|---|
| 00 | `00_plain_agent.py` | A plain agent with no harness | The agent in a bare while-loop: no step limit, no error handling. Crashes on the first tool error. |
| 01 | `01_harness_vs_agent.py` | Harness as the control layer · Harness vs agent responsibilities | The same agent and question inside a LangGraph graph: the error becomes data and the agent recovers. Prints a "who does what" table. |
| 02 | `02_context_session_io.py` | Context manager · Session state · Input/output handling | Input cleaning, context window trimming, name remembered via session state, separate sessions per `thread_id`, JSON output. |
| 03 | `03_runtime_lifecycle.py` | Agent runtime & lifecycle | `CREATED → RUNNING → WAITING_FOR_HUMAN → COMPLETED/FAILED`, streamed steps, pause/resume with `interrupt()`, step budget. |
| 04 | `04_tool_manager.py` | Tool manager: registration & invocation | Registry with tags, tool schemas the LLM sees, validation of bad args/unknown tools, enable/disable at runtime. |
| 05 | `05_errors_retries_timeouts.py` | Error handling, retries, timeouts | Retry with exponential backoff, no retry on permanent errors, timeouts with graceful fallback, LangGraph `RetryPolicy`. |
| 06 | `06_guardrails.py` | Basic guardrails | Prompt-injection block, Aadhaar/PAN/phone/email redaction, tool allow-list, secret redaction in output. |
| 07 | `07_logging_tracing.py` | Structured logging & execution tracing | JSON logs with `trace_id`, per-node/tool spans, timeline view, `trace.jsonl` export. |
| 08 | `08_mini_harness.py` | **Everything combined** | "Campus Helper" harness: all of the above in ~300 lines. |

Run them in order, from `src/`:

```bash
cd src
uv run 00_plain_agent.py
uv run 01_harness_vs_agent.py
uv run 02_context_session_io.py
...
uv run 08_mini_harness.py
```

Demos 01–08 also save a picture of their graph to `diagrams/<demo>.png` (via `graph.get_graph().draw_mermaid_png()`). Rendering uses the mermaid.ink web service, so offline the demo saves the Mermaid text as `diagrams/<demo>.mmd` instead. Paste that into https://mermaid.live to see it drawn.

`common.py` holds the shared tools (`calculator`, `get_weather` via Open-Meteo, `get_time`, `web_search` via Tavily), `get_llm()`, and `save_graph_png()` for the diagrams. `offline_llm.py` is the fake LLM used when there's no key. Trainees don't need to read it.

## Suggested teaching flow (≈ 3 hours)

1. **00 + 01** (20 min) — run 00 first and let it crash. Ask: "whose job was it to handle that?" Then run 01.
2. **02** (25 min) — do the "Try this" at the end: remove the name injection and watch the agent forget.
3. **03** (25 min) — draw the lifecycle diagram from the docstring on the board before running.
4. **04** (20 min) — have students add their own tool with `@tm.tool(...)`.
5. **05** (25 min) — discuss which errors deserve a retry and which don't.
6. **06** (20 min) — students try to sneak past the guardrails; discuss why regex isn't enough.
7. **07** (20 min) — open `trace.jsonl` and find the slowest step.
8. **08** (25 min) — walk the file top-to-bottom; every section maps back to a demo.

## Exercises

- **00:** Add a `recursion_limit` to the naive loop. What else would you need to copy over?
- **02:** Replace `token_counter=len` with a real token count (`token_counter="approximate"`) and set a budget of 300 tokens.
- **03:** Add a `CANCELLED` state and a `cancel()` method.
- **04:** Add a `get_forecast(city, days)` tool using Open-Meteo's `daily=temperature_2m_max,temperature_2m_min` parameters (reuse the geocoding step from `get_weather` in `common.py`), and register it with the `info` tag.
- **05:** Add a **circuit breaker**: after 5 consecutive failures, skip the tool for 30 seconds.
- **06:** Add a topic guard that refuses non-study questions.
- **07:** Add token usage per run (with a real LLM, read `ai.usage_metadata`).
- **08:** Swap `InMemorySaver` for `SqliteSaver` (`uv add langgraph-checkpoint-sqlite`) and show that sessions survive a restart. Then wrap `harness.chat()` in a FastAPI endpoint.

## Notes for instructors

- Tested with `langgraph 1.2`, `langchain-core 1.7`, Python 3.11+. Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`; commit both so every student gets identical versions.
- To bump dependencies before a new batch: `uv lock --upgrade && uv sync`, then re-run the demos.
- Before class, check that the network allows `api.openai.com`, `api.open-meteo.com` and `geocoding-api.open-meteo.com`. If many trainees share one key, expect occasional rate-limit (429) errors.
- With a real LLM the wording of answers changes from run to run, but the harness behaviour is the same. If the API is blocked, run without a key (`OPENAI_API_KEY= uv run <demo>.py` from `src/`) to get the fake LLM's canned answers.
- The demo prompts are worded so a real model actually attempts the action being taught: a harmless email for the human to reject, an explicit file path to delete, a fake city (Hogwarts, Mordor) that the weather API can't find. With vaguer prompts a sensible model refuses or asks a follow-up question, and the harness feature never runs.
- Demo 05 takes ~10 seconds because it waits on timeouts on purpose.
- LangGraph's native `add_node(..., timeout=...)` only works for **async** nodes; demo 05 shows a thread-based timeout that works with plain sync code.
