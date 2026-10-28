"""
DEMO 05 — Error handling, retries and timeouts

Things WILL fail: APIs time out, networks drop, LLM providers return 429/500,
the LLM passes bad arguments. The harness decides what to do:

  ┌──────────────────────┬─────────────────────────────┬──────────────────────┐
  │ Error type           │ Example                     │ Harness reaction     │
  ├──────────────────────┼─────────────────────────────┼──────────────────────┤
  │ Transient            │ ConnectionError, 503, 429   │ RETRY with backoff   │
  │ Slow / hanging       │ API never responds          │ TIMEOUT, then retry  │
  │ Permanent / bad input│ ValueError, unknown symbol  │ DON'T retry → tell   │
  │                      │                             │ the agent (it may fix│
  │                      │                             │ its arguments)       │
  │ Out of retries       │ still failing after N tries │ GRACEFUL FALLBACK    │
  └──────────────────────┴─────────────────────────────┴──────────────────────┘

Two layers shown:
  A. Tool level  — our own `call_with_policy()` (retry + backoff + timeout)
  B. Node level  — LangGraph's built-in RetryPolicy on the LLM node

Run:  uv run 05_errors_retries_timeouts.py   (takes ~10 s because of timeouts)
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition
from langgraph.types import RetryPolicy

from common import HumanMessage, ToolMessage, banner, get_llm, save_graph_png

# ── Unreliable tools (simulated, deterministic for the classroom) ─────
_attempts = {"stock": 0, "report": 0}


@tool
def get_stock_price(symbol: str) -> str:
    """Get the latest NSE stock price for a symbol, e.g. INFY or TCS."""
    _attempts["stock"] += 1
    if symbol not in {"INFY", "TCS", "RELIANCE"}:
        raise ValueError(f"Unknown NSE symbol '{symbol}'")  # permanent error
    if _attempts["stock"] % 3 != 0:  # fails 2 of 3 times
        raise ConnectionError("NSE API: connection reset")  # transient error
    return f"{symbol}: ₹{random.Random(symbol).randint(1500, 4000)}.00"


@tool
def generate_report(topic: str) -> str:
    """Generate an analytics report on a topic (slow backend)."""
    _attempts["report"] += 1
    time.sleep(3)  # always slower than our 1 s timeout
    return f"Report on {topic}: ..."


TOOLS = {t.name: t for t in (get_stock_price, generate_report)}


# ── A. Tool-level policy: retry + exponential backoff + timeout ───────
RETRYABLE = (ConnectionError, TimeoutError)
_pool = ThreadPoolExecutor(max_workers=4)


def call_with_policy(fn, args, *, max_attempts=3, base_delay=0.3, timeout_s=1.0):
    """Run a tool with retries, backoff and a hard timeout.
    Returns (ok: bool, output: str)."""
    for attempt in range(1, max_attempts + 1):
        try:
            future = _pool.submit(fn.invoke, args)
            out = future.result(timeout=timeout_s)  # ⏱️ hard timeout
            print(f"      attempt {attempt}: ✅ success")
            return True, out
        except FutureTimeout:
            err = TimeoutError(f"timed out after {timeout_s}s")
            # Note: Python threads can't be killed — the slow call keeps running
            # in the background; we just stop WAITING for it.
        except Exception as e:
            err = e
        if not isinstance(err, RETRYABLE):
            print(
                f"      attempt {attempt}: ❌ {type(err).__name__} (permanent → no retry)"
            )
            return False, f"{type(err).__name__}: {err}"
        if attempt < max_attempts:
            delay = base_delay * 2 ** (attempt - 1) + random.uniform(
                0, 0.1
            )  # backoff + jitter
            print(
                f"      attempt {attempt}: ⚠️  {type(err).__name__} → retry in {delay:.2f}s"
            )
            time.sleep(delay)
        else:
            print(f"      attempt {attempt}: ❌ {type(err).__name__} → giving up")
    return (
        False,
        f"Service unavailable after {max_attempts} attempts ({err}). Please try later.",
    )


# ── B. A flaky LLM to show LangGraph's built-in node RetryPolicy ──────
class FlakyLLM:
    """Wraps the real/scripted LLM; first call raises a simulated 503."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            print("   🧠 LLM call #1: ⚠️  simulated 503 Service Unavailable")
            raise ConnectionError("LLM provider 503")
        print(f"   🧠 LLM call #{self.calls}: ✅")
        return self.inner.invoke(messages)


llm = FlakyLLM(get_llm().bind_tools(list(TOOLS.values())))


def agent_node(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


def resilient_tool_node(state: MessagesState):
    out = []
    for call in state["messages"][-1].tool_calls:
        print(f"   🔧 {call['name']}({call['args']})")
        ok, result = call_with_policy(TOOLS[call["name"]], call["args"])
        out.append(
            ToolMessage(
                result if ok else f"Error: {result}",
                tool_call_id=call["id"],
                status="success" if ok else "error",
            )
        )
    return {"messages": out}


builder = StateGraph(MessagesState)
builder.add_node(
    "agent",
    agent_node,
    retry_policy=RetryPolicy(
        max_attempts=3, initial_interval=0.2, retry_on=ConnectionError
    ),
)  # built-in!
builder.add_node("tools", resilient_tool_node)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
graph = builder.compile()
save_graph_png(graph, "05_errors_retries_timeouts.png")

# Native alternative: add_node(..., timeout=5) works for ASYNC nodes in LangGraph.


def run(question):
    res = graph.invoke({"messages": [HumanMessage(question)]}, {"recursion_limit": 10})
    print(f"   🤖 {res['messages'][-1].content}")


banner("Case 1 — transient errors: LLM 503 + tool fails twice → retries succeed")
run("What is the stock price of INFY?")

banner("Case 2 — permanent error: bad symbol → no retry, agent is informed")
run("What is the stock price of XYZ?")

banner("Case 3 — slow backend: every attempt times out → graceful fallback")
llm.calls = 1  # skip the simulated LLM failure this time
run("Generate a report on monthly sales")
