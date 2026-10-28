"""
A LangChain agent that uses our MCP server.

    YOU ──▶ LangChain agent (this file) ── HTTP ──▶ MCP server (../mcp_server)
              │                                       ├─ tools
              └─ the OpenAI model decides             ├─ resource
                 which tool to call                   └─ prompt

What this file shows, step by step:
    1. Connect to the MCP server over Streamable HTTP
    2. Read a RESOURCE      (info://about)
    3. Load the TOOLS and give them to an agent
    4. Use a PROMPT         (weather_report)
    5. Chat with the agent  (type "quit" to stop)

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
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()  # reads OPENAI_API_KEY and MCP_API_KEY from .env

MODEL = "openai:gpt-5-mini"  # any OpenAI chat model your key can use
MCP_URL = "http://127.0.0.1:9001/mcp"


def print_tool_calls(messages):
    """Show which MCP tools the agent called, so you can see MCP at work."""
    for message in messages:
        for call in getattr(message, "tool_calls", []):
            print(f"   🔧 {call['name']}({call['args']})")


async def main():
    # 1. Connect. One client can talk to many MCP servers; we have just one.
    #    Our server is protected, so every request carries the API key in the
    #    Authorization header. Without it the server answers 401 Unauthorized.
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

    # 3. Load the tools. Each MCP tool becomes a LangChain tool, with the same
    #    name, description and input schema the server published.
    tools = await client.get_tools()
    print("🧰 Tools from the server:", [tool.name for tool in tools], "\n")

    agent = create_agent(
        model=MODEL,
        tools=tools,
        system_prompt="You are a helpful assistant. Use the tools to answer questions about weather, products and users.",
    )

    # 4. Use a prompt. The server returns ready-made messages; we pass them to the agent.
    prompt_messages = await client.get_prompt("my-mcp-server", "weather_report", arguments={"city": "Mumbai"})
    print("💬 Prompt weather_report(city='Mumbai'):", prompt_messages[0].content)
    result = await agent.ainvoke({"messages": prompt_messages})
    print_tool_calls(result["messages"])
    print("🤖", result["messages"][-1].text, "\n")

    # 5. Chat. We keep the whole conversation in `messages`, so the agent remembers it.
    print("Ask about weather, products or users. Type 'quit' to stop.")
    messages = []
    while True:
        question = input("You: ").strip()
        if question.lower() in ("quit", "exit"):
            break
        if not question:
            continue

        messages.append({"role": "user", "content": question})
        result = await agent.ainvoke({"messages": messages})
        print_tool_calls(result["messages"][len(messages):])  # only this turn's calls
        print("🤖", result["messages"][-1].text, "\n")
        messages = result["messages"]


if __name__ == "__main__":
    asyncio.run(main())
