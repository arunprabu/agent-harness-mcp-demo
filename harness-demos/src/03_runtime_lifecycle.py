"""
DEMO 03 — Agent runtime and lifecycle management

The RUNTIME is the part of the harness that actually *runs* an agent and tracks
where each run is in its life:

     CREATED ──start()──► RUNNING ──► COMPLETED
                             │  ▲
               needs human   │  │ resume()
                             ▼  │
                     WAITING_FOR_HUMAN ──reject──► (agent told "denied") ──► COMPLETED
                             │
                 error / step budget exceeded ──► FAILED

We show:
  • streaming each step as it happens (so a UI can show progress)
  • a step budget (recursion_limit) that stops runaway agents
  • PAUSE & RESUME with LangGraph interrupt() — human approval before a risky tool
  • lifecycle hooks (on_start / on_finish) and run metadata (duration, steps)

Run:  uv run 03_runtime_lifecycle.py
"""

import time
import uuid
from enum import Enum

from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from common import ALL_TOOLS, HumanMessage, ToolMessage, banner, get_llm, save_graph_png


@tool
def send_email(to: str, body: str) -> str:
    """Send an email to a recipient. (Side effect! Needs approval.)"""
    return f"📧 Email sent to {to}"


TOOLS = ALL_TOOLS + [send_email]
SENSITIVE_TOOLS = {"send_email"}
llm = get_llm().bind_tools(TOOLS)


# ── The graph: agent → (approval if needed) → tools → agent ───────────
def agent_node(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


def route(state: MessagesState):
    calls = state["messages"][-1].tool_calls
    if not calls:
        return END
    return "approval" if any(c["name"] in SENSITIVE_TOOLS for c in calls) else "tools"


def approval_node(state: MessagesState):
    """Pauses the run until a human approves. State is checkpointed meanwhile."""
    calls = state["messages"][-1].tool_calls
    decision = interrupt(
        {  # ⏸️  run stops HERE
            "question": "Approve these tool calls?",
            "calls": [{"tool": c["name"], "args": c["args"]} for c in calls],
        }
    )
    if decision == "approve":
        return Command(goto="tools")
    # Rejected → give the agent a tool result explaining why, let it respond
    denied = [
        ToolMessage(
            f"Action '{c['name']}' was rejected by a human reviewer.",
            tool_call_id=c["id"],
        )
        for c in calls
    ]
    return Command(goto="agent", update={"messages": denied})


builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
builder.add_node("approval", approval_node, destinations=("tools", "agent"))
builder.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route, ["approval", "tools", END])
builder.add_edge("tools", "agent")
graph = builder.compile(checkpointer=InMemorySaver())  # needed for pause/resume
save_graph_png(graph, "03_runtime_lifecycle.png")


# ── The runtime: owns the lifecycle of each run ───────────────────────
class Status(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentRun:
    def __init__(self, graph, max_steps=10):
        self.graph = graph
        self.run_id = uuid.uuid4().hex[:8]
        self.config = {
            "configurable": {"thread_id": self.run_id},
            "recursion_limit": max_steps,
        }
        self.status = Status.CREATED
        self.steps = 0
        self.pending = None
        self.answer = None
        self._t0 = None
        self._log(f"created (step budget = {max_steps})")

    def _log(self, msg):
        print(f"   [run {self.run_id} | {self.status.value:<17}] {msg}")

    def _set(self, status):
        self.status = status
        self._log(f"→ {status.value}")

    # lifecycle hooks — the place to emit metrics, notify a UI, bill usage...
    def on_start(self):
        self._t0 = time.perf_counter()

    def on_finish(self):
        self._log(
            f"finished in {time.perf_counter() - self._t0:.2f}s after {self.steps} steps"
        )

    def _drive(self, graph_input):
        self._set(Status.RUNNING)
        try:
            for update in self.graph.stream(
                graph_input, self.config, stream_mode="updates"
            ):
                for node, _ in update.items():
                    if node == "__interrupt__":
                        self.pending = update["__interrupt__"][0].value
                        self._set(Status.WAITING_FOR_HUMAN)
                        self._log(f"needs approval for: {self.pending['calls']}")
                        return self
                    self.steps += 1
                    self._log(f"step {self.steps}: '{node}' done")
            self.answer = (
                self.graph.get_state(self.config).values["messages"][-1].content
            )
            self._set(Status.COMPLETED)
        except GraphRecursionError:
            self._set(Status.FAILED)
            self._log("❌ step budget exceeded — stopped a runaway agent")
        except Exception as e:
            self._set(Status.FAILED)
            self._log(f"❌ {type(e).__name__}: {e}")
        self.on_finish()
        return self

    def start(self, task):
        self.on_start()
        return self._drive({"messages": [HumanMessage(task)]})

    def resume(self, decision):
        assert self.status == Status.WAITING_FOR_HUMAN, "nothing to resume"
        self._log(f"human said: {decision}")
        return self._drive(Command(resume=decision))


banner("Run 1 — normal task, streamed step by step")
run = AgentRun(graph).start("What's the weather in Mumbai?")
print(f"   ✅ answer: {run.answer}")

# banner("Run 2 — risky tool → PAUSE → human APPROVES → resume")
# run = AgentRun(graph).start("Send an email to boss@example.com saying the build is green")
# run.resume("approve")
# print(f"   ✅ answer: {run.answer}")

# banner("Run 3 — risky tool → PAUSE → human REJECTS → agent is told")
# run = AgentRun(graph).start("Send an email to team@example.com saying the office is closed tomorrow")
# run.resume("reject")
# print(f"   ✅ answer: {run.answer}")

# banner("Run 4 — step budget too small → FAILED (instead of looping forever)")
# AgentRun(graph, max_steps=2).start("What is the weather in Delhi and what is 7*6?")
