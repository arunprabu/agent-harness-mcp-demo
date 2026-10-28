# CLAUDE.md

Never access .env
But you can access .env.example

Teaching material: a numbered series of LangGraph scripts, each demonstrating one agent-harness concept to fresh engineers. `README.md` has the demo table, teaching flow, and exercises. Read it before changing course content.

## Commands

```bash
uv sync                         # install pinned deps from uv.lock (Python 3.12 via .python-version)
uv run 01_harness_vs_agent.py   # run any demo; no venv activation needed
uv add <pkg>                    # add a dependency (updates pyproject.toml + uv.lock)
OPENAI_API_KEY= uv run <demo>.py   # run on the fake offline LLM instead of the real one
```

The empty `OPENAI_API_KEY=` works because `load_dotenv()` never overrides a variable that's already set.

There are no tests or linters. Verify a change by running the affected demo(s), and `08_mini_harness.py` too if you touched a concept it combines. Demo 05 takes about 10 s on purpose because it waits on timeouts. Demo 07 writes `trace.jsonl` to the working directory. Demos 01–08 write their graph diagrams to `diagrams/`.

## How it fits together

- `common.py` holds the shared tools (`calculator`, `get_weather`, `get_time`, `web_search`), `get_llm()`, `banner()`, and `save_graph_png()`. `get_weather` calls Open-Meteo live: geocoding first, then the forecast. Demos import from it with `from common import ...`.
- Every graph demo (01–08) calls `save_graph_png(graph, "<demo>.png")` right after compiling its graph. A new graph should do the same. Demo 00 has no graph. When `add_conditional_edges` routes with a lambda, pass a path map (the list of possible destinations). Without one, the diagram draws an edge from that node to every other node.
- `get_llm()` returns a real model (`init_chat_model`, default `openai:gpt-4.1-mini`) when `OPENAI_API_KEY` or `MODEL` is set. With no key it falls back to `ScriptedLLM` in `offline_llm.py`, a keyword-rule fake that trainees aren't meant to read.
- Demos 00–07 each stand alone. 00 and 01 are a pair: the same agent and question, without and then with a harness, so keep `QUESTION` the same in both. Demo-specific tools such as `send_email`, `get_stock_price`, and `delete_file` are defined inside the demo that uses them.
- `08_mini_harness.py` re-implements the pieces from 02–07 inline (Tracer, ToolManager, Guardrails, Runtime) and does not import them. The numbered filenames aren't importable anyway. If you change a concept in an earlier demo, check whether 08 needs the same change.

## Rules that keep the class working

- **The real LLM is the default, so each prompt must get it to attempt the action being taught.** A sensible model refuses risky requests and asks a follow-up on vague ones, and then the harness feature never runs. For example, an email with a salary sheet was refused, so demo 03 never paused for approval. Make the action harmless and explicit, and run the demo with the real model after changing a prompt.
- Fake cities for the weather-error scenario must be names Open-Meteo can't geocode. Atlantis, Narnia, Gotham and Wakanda all resolve to real places; Hogwarts and Mordor don't.
- **The no-key fallback must keep working.** If you add a tool or a demo question, add a matching rule in `ScriptedLLM._plan()` in `offline_llm.py`. Then run the demo with `OPENAI_API_KEY=` to confirm.
- `ScriptedLLM.bind_tools()` filters planned calls to the bound tools only, the way a real model behaves. A rule for a tool that isn't bound is silently dropped.
- Simulated failures (the flaky tools in 05 and 08) are deterministic on purpose, so every student sees the same output. Don't add real randomness.
- `get_weather` needs internet. A live call takes about 1–2 s, so demo 08's ToolManager allows 5 s per tool. Don't lower that, or the weather call times out on a slow network.
- `load_dotenv()` reads only `.env`, so values in `.env.local` are **not** loaded. Put keys in `.env`, copied from `.env.example`.

## Style

This code is read aloud in class, so readability comes before cleverness:

- Each file opens with a long module docstring: the concept, an ASCII diagram, and a `Run:` line. Keep it accurate when you change behaviour.
- Sections are separated with box-drawing comment headers (`# ── Name ───` or `# ═══`).
- Output is meant for a classroom terminal: `banner()` headings, emoji status markers, explanatory prints.
- Keep each demo focused on one concept, and avoid abstractions that hide what the harness is doing.
- If you change demo behaviour, update the matching row, teaching-flow step, or exercise in `README.md`.
