"""
DEMO 07 — Structured logging and execution tracing

print("something happened") is useless at 2 AM in production. We want:

  STRUCTURED LOGS  : one JSON object per event → searchable in tools like
                     ELK, Loki, CloudWatch, Datadog.
                     e.g.  {"trace_id": "a1b2", "event": "tool_end", "tool": "get_weather", "duration_ms": 3.2}
  TRACE            : every event of ONE request shares a trace_id, and each
                     step is a SPAN with start/end/duration. Together they
                     show the full story of a run as a timeline.

How it's done here:
  • a JSON log formatter (standard `logging` module)
  • a `trace_id` stored in a contextvar → automatically added to every log line
  • a @traced decorator wrapped around each graph node → node_start / node_end
  • spans collected in memory → printed as a timeline + saved to trace.jsonl

Production equivalents: LangSmith (set LANGSMITH_TRACING=true + LANGSMITH_API_KEY,
zero code changes) or OpenTelemetry / Langfuse.

Run:  uv run 07_logging_tracing.py
"""

import contextvars
import functools
import json
import logging
import sys
import time
import uuid

from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition

from common import ALL_TOOLS, HumanMessage, ToolMessage, banner, get_llm, save_graph_png

# ── 1. Structured JSON logger ─────────────────────────────────────────
trace_id_var = contextvars.ContextVar("trace_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": time.strftime("%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "trace_id": trace_id_var.get(),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, ensure_ascii=False, default=str)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger("harness")
log.addHandler(handler)
log.setLevel(logging.INFO)


def emit(event, level=logging.INFO, **fields):
    log.log(level, event, extra={"fields": fields})


# ── 2. Span collection + @traced decorator ────────────────────────────
SPANS: list[dict] = []


def traced(kind):
    """Wrap a function so every call becomes a span with timing + logs."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            name = kwargs.pop("_span_name", fn.__name__)
            span = {
                "trace_id": trace_id_var.get(),
                "span_id": uuid.uuid4().hex[:6],
                "kind": kind,
                "name": name,
                "start": time.perf_counter(),
            }
            emit(f"{kind}_start", name=name)
            try:
                result = fn(*args, **kwargs)
                span["status"] = "ok"
                return result
            except Exception as e:
                span["status"] = "error"
                span["error"] = str(e)
                emit(f"{kind}_error", logging.ERROR, name=name, error=str(e))
                raise
            finally:
                span["duration_ms"] = round(
                    (time.perf_counter() - span["start"]) * 1000, 2
                )
                SPANS.append(span)
                emit(
                    f"{kind}_end",
                    name=name,
                    status=span["status"],
                    duration_ms=span["duration_ms"],
                )

        return wrapper

    return deco


# ── 3. Agent graph with traced nodes and traced tool calls ────────────
llm = get_llm().bind_tools(ALL_TOOLS)
TOOLS = {t.name: t for t in ALL_TOOLS}


@traced("node")
def agent(state: MessagesState):
    ai = llm.invoke(state["messages"])
    emit(
        "llm_decision",
        tool_calls=[c["name"] for c in ai.tool_calls],
        answer_chars=len(ai.content),
        usage=getattr(ai, "usage_metadata", None),
    )  # token counts with real LLMs
    return {"messages": [ai]}


@traced("tool")
def run_tool(call):
    return TOOLS[call["name"]].invoke(call["args"])


@traced("node")
def tools(state: MessagesState):
    out = []
    for call in state["messages"][-1].tool_calls:
        emit("tool_args", tool=call["name"], args=call["args"])
        try:
            result = run_tool(call, _span_name=call["name"])
            out.append(ToolMessage(result, tool_call_id=call["id"]))
        except Exception as e:
            out.append(
                ToolMessage(f"Error: {e}", tool_call_id=call["id"], status="error")
            )
    return {"messages": out}


builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", tools)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
graph = builder.compile()
save_graph_png(graph, "07_logging_tracing.png")


@traced("run")
def handle_request(question):
    return graph.invoke({"messages": [HumanMessage(question)]})


def serve(question):
    trace_id_var.set(uuid.uuid4().hex[:8])  # new trace per request
    emit("request_received", question=question)
    res = handle_request(question, _span_name="handle_request")
    emit("response_sent", answer=res["messages"][-1].content[:80])


banner("Structured logs (one JSON line per event)")
serve("What's the weather in Bengaluru and what is 3500 * 12?")
serve("What's the weather in Mordor?")  # tool error → shows in logs


# ── 4. Render the execution trace as a timeline ───────────────────────
banner("Execution trace timeline")
for tid in dict.fromkeys(s["trace_id"] for s in SPANS):
    spans = sorted((s for s in SPANS if s["trace_id"] == tid), key=lambda s: s["start"])
    t0 = spans[0]["start"]
    print(f"\ntrace {tid}")
    for s in spans:
        indent = {"run": 0, "node": 1, "tool": 2}[s["kind"]]
        offset = (s["start"] - t0) * 1000
        mark = "✅" if s["status"] == "ok" else "❌"
        print(
            f"  {'   ' * indent}{mark} {s['kind']}:{s['name']:<16} "
            f"+{offset:7.2f}ms  ({s['duration_ms']} ms){'  ' + s.get('error', '') if s['status'] != 'ok' else ''}"
        )

with open("trace.jsonl", "w") as f:
    for s in SPANS:
        f.write(json.dumps({k: v for k, v in s.items() if k != "start"}) + "\n")
print("\n💾 spans saved to trace.jsonl — load it in pandas/Excel to analyse runs.")
