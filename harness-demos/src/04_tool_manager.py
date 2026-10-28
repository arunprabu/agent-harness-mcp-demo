"""
DEMO 04 — Tool manager: registration and invocation

The agent only *asks* for a tool ("call get_weather with city=Pune").
The TOOL MANAGER (harness) owns the tools:

  REGISTRATION
    • a single registry of every tool, with metadata (tags, enabled flag)
    • publishes each tool's SCHEMA (name, description, arguments) to the LLM
    • can enable/disable tools at runtime, or give different agents different tools

  INVOCATION
    • looks up the requested tool (unknown name? → clean error, not a crash)
    • validates arguments against the schema (pydantic does this for us)
    • executes, measures duration, wraps the result in a standard ToolResult
    • turns the result into a ToolMessage the agent can read

We replace LangGraph's prebuilt ToolNode with our own tool node that uses the
manager, so you can see exactly what happens inside.

Run:  uv run 04_tool_manager.py
"""

import json
import time
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import tools_condition

from common import (
    HumanMessage,
    ToolMessage,
    banner,
    calculator,
    get_llm,
    get_time,
    get_weather,
    save_graph_png,
    web_search,
)


# ── The Tool Manager ──────────────────────────────────────────────────
@dataclass
class ToolResult:
    tool: str
    ok: bool
    output: str
    duration_ms: float


@dataclass
class RegisteredTool:
    tool: BaseTool
    tags: set = field(default_factory=set)
    enabled: bool = True
    calls: int = 0


class ToolManager:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    # ---------- registration ----------
    def register(self, t: BaseTool, tags=()):
        if t.name in self._tools:
            raise ValueError(f"Tool '{t.name}' already registered")
        self._tools[t.name] = RegisteredTool(t, set(tags))
        print(f"   ➕ registered {t.name:<16} tags={sorted(tags)}")
        return t

    def tool(self, tags=()):
        """Decorator: define AND register a tool in one step."""

        def wrap(fn):
            return self.register(tool(fn), tags)

        return wrap

    def disable(self, name):
        self._tools[name].enabled = False
        print(f"   🚫 disabled {name}")

    def get_tools(self, tags=None):
        """Tools to bind to an agent — optionally only those with certain tags."""
        return [
            r.tool
            for r in self._tools.values()
            if r.enabled and (tags is None or r.tags & set(tags))
        ]

    def describe(self):
        """What the LLM actually 'sees' about each tool."""
        for r in self._tools.values():
            flag = "✅" if r.enabled else "🚫"
            print(f"   {flag} {r.tool.name}: {r.tool.description.splitlines()[0]}")
            print(f"        args schema: {json.dumps(r.tool.args)}")

    # ---------- invocation ----------
    def invoke(self, name, args) -> ToolResult:
        t0 = time.perf_counter()
        reg = self._tools.get(name)
        if reg is None:
            return ToolResult(name, False, f"Unknown tool '{name}'", 0)
        if not reg.enabled:
            return ToolResult(name, False, f"Tool '{name}' is disabled", 0)
        try:
            out = reg.tool.invoke(args)  # pydantic validates args here
            ok = True
        except Exception as e:  # validation OR runtime error
            short = " ".join(str(e).splitlines()[:3])  # keep error messages short
            out, ok = f"{type(e).__name__}: {short}", False
        reg.calls += 1
        return ToolResult(
            name, ok, str(out), round((time.perf_counter() - t0) * 1000, 2)
        )

    def stats(self):
        return {n: r.calls for n, r in self._tools.items()}


# ── Register tools ────────────────────────────────────────────────────
banner("1. REGISTRATION")
tm = ToolManager()
tm.register(calculator, tags=["math"])
tm.register(get_weather, tags=["info"])
tm.register(get_time, tags=["info"])
tm.register(web_search, tags=["info", "web"])  # Tavily-backed


@tm.tool(tags=["finance"])
def convert_currency(
    amount: float, from_currency: str, to_currency: str = "INR"
) -> str:
    """Convert money between currencies (demo fixed rates)."""
    rates_to_inr = {"INR": 1, "USD": 88.0, "EUR": 102.0, "GBP": 117.0}  # demo values
    inr = amount * rates_to_inr[from_currency.upper()]
    return f"{amount} {from_currency.upper()} = {inr / rates_to_inr[to_currency.upper()]:.2f} {to_currency.upper()}"


banner("2. WHAT THE LLM SEES (tool schemas)")
tm.describe()


# ── Direct invocation (no LLM) — test the manager on its own ──────────
banner("3. INVOCATION — the manager handles good and bad calls")
for name, args in [
    ("calculator", {"expression": "1200 * 1.18"}),
    ("convert_currency", {"amount": 50, "from_currency": "USD"}),
    ("convert_currency", {"amount": "fifty", "from_currency": "USD"}),  # bad arg type
    ("get_weather", {}),  # missing arg
    ("book_flight", {"to": "Goa"}),  # unknown tool
]:
    print(f"   {name}({args})\n      → {tm.invoke(name, args)}")


# ── Use the manager inside a LangGraph agent ──────────────────────────
def build_agent(manager: ToolManager, tags=None):
    tools = manager.get_tools(tags)
    llm = get_llm().bind_tools(tools)  # agent only knows THESE tools

    def agent_node(state: MessagesState):
        return {"messages": [llm.invoke(state["messages"])]}

    def tool_node(state: MessagesState):  # our own ToolNode
        out = []
        for call in state["messages"][-1].tool_calls:
            r = manager.invoke(call["name"], call["args"])
            print(f"   🔧 {r.tool} ok={r.ok} {r.duration_ms}ms")
            out.append(
                ToolMessage(
                    r.output if r.ok else f"Error: {r.output}",
                    tool_call_id=call["id"],
                    name=r.tool,
                    status="success" if r.ok else "error",
                )
            )
        return {"messages": out}

    b = StateGraph(MessagesState)
    b.add_node("agent", agent_node)
    b.add_node("tools", tool_node)
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", tools_condition)
    b.add_edge("tools", "agent")
    return b.compile()


banner("4. AGENT using the tool manager")
agent = build_agent(tm)
save_graph_png(agent, "04_tool_manager.png")
res = agent.invoke(
    {
        "messages": [
            HumanMessage("Search the latest news on LangGraph and tell me the time")
        ]
    }
)
print(res["messages"][-1].content)

banner("5. RUNTIME CONTROL — disable web search, restrict an agent by tag")
tm.disable("web_search")
math_agent = build_agent(tm, tags=["math"])  # only sees calculator
res = math_agent.invoke(
    {"messages": [HumanMessage("Search the news and what is 99 * 12?")]}
)
print(res["messages"][-1].content)
print(f"\n   📈 call counts: {tm.stats()}")
