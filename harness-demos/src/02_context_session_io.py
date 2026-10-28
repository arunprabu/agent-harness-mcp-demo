"""
DEMO 02 — Context manager, session state and input/output handling

Three harness jobs that happen around EVERY agent call:

  1. INPUT HANDLING   : clean & validate raw user input before the agent sees it.
  2. CONTEXT MANAGER  : decide WHAT the LLM sees this turn. LLMs have a limited
                        context window (and you pay per token), so we send a
                        system prompt + only the last few messages — not the
                        whole history.
  3. SESSION STATE    : what the harness remembers between turns (full history,
                        user's name, turn count). Stored by a checkpointer and
                        keyed by thread_id → each user/session is isolated.
  4. OUTPUT HANDLING  : turn the agent's raw message into a clean, structured
                        response for the app (e.g. JSON for a FastAPI endpoint).

Graph:  START → input → agent ⇄ tools → output → END

Run:  uv run 02_context_session_io.py
"""

import re
from typing import Optional

from langchain_core.messages import trim_messages
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from common import (
    ALL_TOOLS,
    HumanMessage,
    SystemMessage,
    banner,
    get_llm,
    save_graph_png,
)

llm = get_llm().bind_tools(ALL_TOOLS)

MAX_INPUT_CHARS = 500
CONTEXT_WINDOW_MESSAGES = 4  # tiny on purpose so you can SEE trimming happen


# ── Session state: everything the harness remembers for one session ──
class AgentState(MessagesState):  # MessagesState gives us `messages`
    user_input: str  # raw input for this turn
    user_name: Optional[str]  # structured memory (survives trimming!)
    turn_count: int
    output: dict  # final structured response


# ── 1. INPUT HANDLING ──────────────────────────────────────────────────
def input_node(state: AgentState):
    raw = state["user_input"]
    text = " ".join(raw.split())  # normalise whitespace
    if not text:
        text = "(empty message)"
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + " …[truncated]"

    update = {
        "messages": [HumanMessage(text)],
        "turn_count": state.get("turn_count", 0) + 1,
    }
    # Extract a durable fact into session state
    if m := re.search(r"my name is (\w+)", text, re.I):
        update["user_name"] = m.group(1).title()
    return update


# ── 2. CONTEXT MANAGER ─────────────────────────────────────────────────
def build_context(state: AgentState):
    """Return the list of messages the LLM will actually see this turn."""
    system = "You are a helpful assistant for Indian users. Be concise."
    if state.get("user_name"):
        system += f" The user's name is {state['user_name']}."  # inject memory

    recent = trim_messages(
        state["messages"],
        max_tokens=CONTEXT_WINDOW_MESSAGES,
        token_counter=len,  # count MESSAGES (use a real tokenizer in production)
        strategy="last",  # keep the most recent
        start_on="human",  # never start the window on a dangling tool result
    )
    return [SystemMessage(system)] + recent


def agent_node(state: AgentState):
    context = build_context(state)
    print(
        f"   🧠 context sent to LLM: {len(context)} msgs "
        f"(full history in state: {len(state['messages'])})"
    )
    return {"messages": [llm.invoke(context)]}


def route_after_agent(state: AgentState):
    return "tools" if state["messages"][-1].tool_calls else "output"


# ── 4. OUTPUT HANDLING ─────────────────────────────────────────────────
def output_node(state: AgentState):
    final = state["messages"][-1]
    used = sorted({m.name for m in state["messages"] if m.type == "tool"})
    return {
        "output": {
            "answer": final.content.strip(),
            "turn": state["turn_count"],
            "user_name": state.get("user_name"),
            "tools_used_in_session": used,
        }
    }


builder = StateGraph(AgentState)
builder.add_node("input", input_node)
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(ALL_TOOLS, handle_tool_errors=True))
builder.add_node("output", output_node)
builder.add_edge(START, "input")
builder.add_edge("input", "agent")
builder.add_conditional_edges("agent", route_after_agent, ["tools", "output"])
builder.add_edge("tools", "agent")
builder.add_edge("output", END)

# ── 3. SESSION STATE: the checkpointer saves state after every step ────
# InMemorySaver for demos. In production: SqliteSaver / PostgresSaver /
# MongoDBSaver (langgraph-checkpoint-mongodb) so sessions survive restarts.
graph = builder.compile(checkpointer=InMemorySaver())
save_graph_png(graph, "02_context_session_io.png")


def chat(thread_id, text):
    print(f"\n👤 [{thread_id}] {text}")
    result = graph.invoke(
        {"user_input": text}, {"configurable": {"thread_id": thread_id}}
    )
    print(f"🤖 {result['output']}")


banner("Session 'arun' — multiple turns, context gets trimmed")
chat("arun", "   Hi!   My name is Arun   ")
chat("arun", "What's the weather in Pune?")
chat("arun", "What is 1499 * 3?")
chat(
    "arun", "What is my name?"
)  # name message is OUT of the window, but in session state

banner("Session 'priya' — completely separate state")
chat("priya", "What is my name?")

banner("Inspecting saved session state")
snap = graph.get_state({"configurable": {"thread_id": "arun"}})
print(
    f"thread 'arun': {len(snap.values['messages'])} messages stored, "
    f"user_name={snap.values['user_name']!r}, turns={snap.values['turn_count']}"
)
history = list(graph.get_state_history({"configurable": {"thread_id": "arun"}}))
print(
    f"checkpoints saved for 'arun': {len(history)} (one per step → enables replay/debug)"
)

print("""
💡 Try this: remove the `if state.get("user_name")` injection in build_context()
   and re-run. The agent forgets the name, because the message that contained
   it was trimmed out of the context window.
""")
