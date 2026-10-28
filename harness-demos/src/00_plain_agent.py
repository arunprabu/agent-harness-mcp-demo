"""
DEMO 00 — A plain agent with NO harness

Key idea
--------
  AGENT = the LLM's "brain": reads the conversation, DECIDES what to do next
          (answer, or call which tool with which arguments).

Here the agent runs in a naive while-loop and nothing else:
  ❌ no step limit      → could loop forever
  ❌ no error handling  → the first tool error kills the whole run
  ❌ no session memory, no logging

The question asks for the weather in Hogwarts (not a real city → tool error),
so the run crashes. Demo 01 runs the SAME agent on the SAME question inside
a harness.

Run:  uv run 00_plain_agent.py
"""

from common import ALL_TOOLS, HumanMessage, ToolMessage, banner, get_llm

llm = get_llm().bind_tools(ALL_TOOLS)  # ← the AGENT's brain
QUESTION = "What's the weather in Hogwarts and what is 25 * 4?"  # Hogwarts → tool error


def plain_agent(question):
    tools = {t.name: t for t in ALL_TOOLS}
    messages = [HumanMessage(question)]
    while True:  # ❌ no step limit — could loop forever
        ai = llm.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            return ai.content
        for call in ai.tool_calls:
            result = tools[call["name"]].invoke(call["args"])  # ❌ no error handling
            messages.append(ToolMessage(result, tool_call_id=call["id"]))


banner("Agent WITHOUT a harness")
try:
    print(plain_agent(QUESTION))
except Exception as e:
    print(f"💥 CRASH: {type(e).__name__}: {e}")
    print("   The whole run died. No retry, no recovery, no record of what happened.")
