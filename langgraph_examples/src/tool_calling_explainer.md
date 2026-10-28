## Overview

This ex6_tool.py example demonstrates the modern LangGraph-native approach using `ToolNode`.

Instead of manually executing tools, LangGraph's built-in `ToolNode` handles tool execution automatically.

The architecture separates:

- reasoning
- execution

into distinct graph nodes.

---

## How It Works

The architecture follows this flow:

```text
User Message
    ↓
Agent Node (LLM reasoning)
    ↓
ToolNode executes tools
    ↓
Return tool results
    ↓
Agent continues reasoning
```

The workflow loops between:

- `agent`
- `tools`

until no more tool calls exist.

The routing function checks:

```python
if last_message.tool_calls:
```

and conditionally routes execution.

Note that the state must use `messages` with the `add_messages` reducer, because `ToolNode` reads the last message and appends `ToolMessage` results back into that list:

```python
class AgentState(TypedDict):
    messages: Annotated[List, add_messages]
```

---

## Advantages

- Clean architecture
- Less boilerplate
- Framework-native pattern
- Highly scalable
- Easier maintenance
- Better extensibility
- Supports advanced LangGraph features

Easy to integrate:

- memory
- persistence
- retries
- approvals
- interrupts
- streaming
- observability
- checkpoints
- human-in-loop systems

---

## Disadvantages

- Slightly more abstract
- Requires understanding LangGraph architecture
- Less low-level control than manual loops
- The loop is hidden inside the graph, so it is harder to see what is happening while learning

---

## Best Use Cases

- Production AI agents
- Multi-agent systems
- Enterprise AI platforms
- Long-running workflows
- Tool ecosystems
