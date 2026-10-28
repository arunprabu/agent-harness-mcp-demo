"""
A LangGraph agent that uses our MCP server.

The LangChain client (../langchain_client) used create_agent(), which hides
the agent loop. Here we BUILD that loop ourselves, as a graph you can see:

             ┌─────────┐  tool calls?  ┌─────────┐
   START ──▶ │  agent  │ ───── yes ──▶ │  tools  │ ── calls the MCP server over HTTP
             │ (model) │ ◀──────────── │  (MCP)  │
             └─────────┘               └─────────┘
                  │ no: the answer is ready
                  ▼
                 END

What this file shows, step by step (the same steps as the LangChain client):
    1. Connect to the MCP server over Streamable HTTP, sending the API key
    2. Read a RESOURCE      (info://about)
    3. Load the TOOLS and build the graph: an agent node, a tools node, and edges
    4. Use a PROMPT         (weather_report)
    5. Chat. A checkpointer remembers the conversation (type "quit" to stop)

You'll see each step of the graph as it runs:
    [agent] → get_weather({'city': 'Pune'})
    [tools] ← get_weather: {"city": "Pune", "temperature_c": 27.0, ...
    🤖 It's 27°C in Pune right now...

Before you run it:
    1. Start the server:  cd ../mcp_server && uv run server.py
    2. Copy .env.example to .env, then put in your OpenAI API key
       and the same MCP_API_KEY as ../mcp_server/.env

Run:
    uv run agent.py
"""

import asyncio
import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()  # reads OPENAI_API_KEY and MCP_API_KEY from .env

MODEL = "openai:gpt-5-mini"  # any OpenAI chat model your key can use
MCP_URL = "http://127.0.0.1:9001/mcp"
SYSTEM_PROMPT = "You are a helpful assistant. Use the tools to answer questions about weather, products and users."

# Settings for every run of the graph:
#   thread_id       : which conversation to remember. The checkpointer keeps one per thread.
#   recursion_limit : the most steps (node runs) one question may take. It stops an agent
#                     that loops forever and keeps spending tokens. LangGraph's own
#                     default is over 10,000, so always set your own.
CONFIG = {"configurable": {"thread_id": "demo"}, "recursion_limit": 10}


def build_graph(tools):
    """Build the agent loop: START → agent → (tools → agent)* → END."""
    # bind_tools tells the model which tools exist: their names, descriptions
    # and input schemas, exactly as our MCP server published them.
    model = init_chat_model(MODEL).bind_tools(tools)

    # Node 1: the model reads the whole conversation, then either answers
    # or asks for one or more tool calls.
    async def agent(state: MessagesState):
        response = await model.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [response]}  # MessagesState appends it to the conversation

    graph = StateGraph(MessagesState)  # the state is just the list of messages
    graph.add_node("agent", agent)
    # Node 2: ToolNode runs the tool calls the model asked for. Our tools came
    # from the MCP server, so each call is an HTTP request to it.
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    # tools_condition reads the model's last message:
    # it has tool calls → go to "tools"; no tool calls → the answer is ready → END.
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")  # after the tools run, the model reads their results

    # The checkpointer saves the messages after every step, per thread_id.
    # That is the agent's memory: on each turn we send only the NEW message.
    return graph.compile(checkpointer=InMemorySaver())


async def ask(graph, messages):
    """Run the graph on new messages and print each step as it happens."""
    try:
        # stream_mode="updates" gives us {node_name: what_that_node_returned} after each step.
        async for step in graph.astream({"messages": messages}, CONFIG, stream_mode="updates"):
            for node, update in step.items():
                for message in update["messages"]:
                    if node == "tools":
                        status = " (error)" if message.status == "error" else ""
                        preview = " ".join(message.text.split())[:70]  # one short line
                        print(f"   [tools] ← {message.name}{status}: {preview}...")
                    elif message.tool_calls:
                        for call in message.tool_calls:
                            print(f"   [agent] → {call['name']}({call['args']})")
                    else:
                        print(f"🤖 {message.text}\n")
    except GraphRecursionError:
        print(f"⚠️  Stopped: the agent needed more than {CONFIG['recursion_limit']} steps.\n")


async def main():
    # 1. Connect. Our server is protected, so every request carries the API key
    #    in the Authorization header. Without it the server answers 401 Unauthorized.
    #    (For a server that uses OAuth, pass auth=... instead; see ../guides/01_AUTH_NOTES.md.)
    client = MultiServerMCPClient(
        {
            "my-mcp-server": {
                "transport": "streamable_http",
                "url": MCP_URL,
                "headers": {"Authorization": f"Bearer {os.environ['MCP_API_KEY']}"},
            }
        }
    )

    # 2. Read a resource. The APP reads it; the model never asks for it.
    about = await client.get_resources("my-mcp-server", uris=["info://about"])
    print("📄 Resource info://about:\n" + about[0].as_string() + "\n")

    # 3. Load the tools, then build the graph around them.
    tools = await client.get_tools()
    print("🧰 Tools from the server:", [tool.name for tool in tools], "\n")
    graph = build_graph(tools)

    # 4. Use a prompt. The server returns ready-made messages; we run them through the graph.
    prompt_messages = await client.get_prompt("my-mcp-server", "weather_report", arguments={"city": "Mumbai"})
    print("💬 Prompt weather_report(city='Mumbai'):", prompt_messages[0].content)
    await ask(graph, prompt_messages)

    # 5. Chat. The checkpointer already holds the conversation, including the Mumbai
    #    report, so we send only the new question. Try: "Is it warmer in Pune?"
    print("Ask about weather, products or users. Type 'quit' to stop.")
    while True:
        question = input("You: ").strip()
        if question.lower() in ("quit", "exit"):
            break
        if question:
            await ask(graph, [{"role": "user", "content": question}])


if __name__ == "__main__":
    asyncio.run(main())
