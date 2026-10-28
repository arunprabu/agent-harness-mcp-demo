"""
DEMO 01 — The harness as the engineering & control layer around the agent
          + Responsibilities of the harness vs the agent

Key idea
--------
  AGENT   = the LLM's "brain": reads the conversation, DECIDES what to do next
            (answer, or call which tool with which arguments).
  HARNESS = everything around it that makes it SAFE & RELIABLE to run:
            running the loop, executing tools, catching errors, limiting steps,
            remembering sessions, logging...

Demo 00 ran this agent in a naive while-loop and it crashed on the first
tool error. Here the SAME agent answers the SAME question inside a LangGraph
graph (the harness): the error becomes data and the agent recovers.

Run:  uv run 01_harness_vs_agent.py
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from common import ALL_TOOLS, HumanMessage, banner, get_llm, save_graph_png

llm = get_llm().bind_tools(ALL_TOOLS)  # ← the AGENT's brain
QUESTION = "What's the weather in Hogwarts and what is 25 * 4?"  # Hogwarts → tool error


# ─────────────────────────────────────────────────────────────────────
# The agent, wrapped in a LangGraph harness
# ─────────────────────────────────────────────────────────────────────
def agent_node(state: MessagesState):
    """The ONLY thing the agent does: think and decide."""
    return {"messages": [llm.invoke(state["messages"])]}


builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
# Harness: executes tools and turns exceptions into ToolMessages the agent can read
builder.add_node("tools", ToolNode(ALL_TOOLS, handle_tool_errors=True))

builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)  # harness controls the flow
builder.add_edge("tools", "agent")

graph = builder.compile(checkpointer=InMemorySaver())  # harness: session memory
save_graph_png(graph, "01_harness_vs_agent.png")

banner("Same agent INSIDE a LangGraph harness")
config = {
    "configurable": {"thread_id": "demo-01"},  # harness: which session
    "recursion_limit": 10,  # harness: max steps (no infinite loops)
}
result = graph.invoke({"messages": [HumanMessage(QUESTION)]}, config)
for m in result["messages"]:
    m.pretty_print()

banner("WHO DOES WHAT?")
print(f"""
  {'Responsibility':<38}{'Agent (LLM)':<14}{'Harness (code)'}
  {'-' * 66}
  {'Understand the request':<38}{'✅':<14}
  {'Decide which tool + arguments':<38}{'✅':<14}
  {'Write the final answer':<38}{'✅':<14}
  {'Run the loop / decide next node':<38}{'':<14}✅  (graph edges)
  {'Actually execute tools':<38}{'':<14}✅  (ToolNode)
  {'Catch errors, retry, time out':<38}{'':<14}✅  (demo 05)
  {'Limit steps / cost':<38}{'':<14}✅  (recursion_limit)
  {'Remember sessions':<38}{'':<14}✅  (checkpointer)
  {'Trim context, validate I/O':<38}{'':<14}✅  (demo 02)
  {'Block unsafe input/output':<38}{'':<14}✅  (demo 06)
  {'Log & trace every step':<38}{'':<14}✅  (demo 07)

  Rule of thumb: the LLM is non-deterministic, so anything that MUST happen
  every time (safety, limits, logging) belongs in the harness, not the prompt.
""")
