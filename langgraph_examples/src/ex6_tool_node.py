# this example demonstrates how to have the LLM dynamically
# call multiple tools in a single response,
# and how to structure the graph and state for that use case.
# The agent_node relying on should_continue will keep invoking the LLM until there are
# no more tool calls in the response, allowing for complex
# interactions where the LLM can decide to call multiple tools
# in sequence.

# REFER: tool calling tool-explainer.md file in the same directory
from typing import TypedDict, List, Annotated
from langgraph.graph import StateGraph, START, END

# you must use messages in state to use ToolNode
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI  # uv add langchain-openai python-dotenv
from langchain_core.tools import tool
from langchain_mcp_adapters.client import (
    MultiServerMCPClient,
)  # uv add langchain-mcp-adapters
from dotenv import load_dotenv
import requests
import asyncio
import os

load_dotenv()

llm = ChatOpenAI(model="gpt-6.1-sol")

TAVILY_MCP_URL = f"https://mcp.tavily.com/mcp/?tavilyApiKey={os.environ['TAVILY_API_KEY']}"


@tool
def calculator_tool(expression: str):
    """Evaluate Math expression. For all your calculations you must use this function"""
    print("Calling calculator_tool")
    try:
        return str(eval(expression))
    except:
        return "Error in Calculation"


# MCP Adapter: connect to the Tavily MCP server and load its tools
# (tavily_search, tavily_extract, ...) as LangChain tools
mcp_client = MultiServerMCPClient(
    {
        "tavily": {
            "url": TAVILY_MCP_URL,
            "transport": "streamable_http",
        }
    }
)
tavily_tools = asyncio.run(mcp_client.get_tools())
print("Tavily MCP tools:", [t.name for t in tavily_tools])

tools = [calculator_tool] + tavily_tools

# Bind the tools to LLM
llm_with_tools = llm.bind_tools(tools)


# Custom State
class AgentState(TypedDict):
    messages: Annotated[List, add_messages]


# MCP tools are async-only, so the graph nodes are async and we use ainvoke
async def agent_node(state: AgentState):
    print("Agent is thinking...")

    response = await llm_with_tools.ainvoke(state["messages"])

    return {"messages": [response]}


def should_continue(state: AgentState):
    print("Calling Should continue")
    last_message = state["messages"][-1]

    if last_message.tool_calls:
        return "MORE_TOOLS_TO_CALL"

    return "ALL_TOOL_CALLS_OVER"


# Initialize tool node
tool_node = ToolNode(tools)

# building the graph
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {"MORE_TOOLS_TO_CALL": "tools", "ALL_TOOL_CALLS_OVER": END},
)

workflow.add_edge("tools", "agent")
app = workflow.compile()


# generating and saving the graph visualization
graph_image = app.get_graph().draw_mermaid_png()
with open("src/ex6_tool_node.png", "wb") as f:
    f.write(graph_image)


# result = app.invoke(
#     {
#         "messages": [
#             {
#                 "role": "user",
#                 "content": "Hey",
#             }
#         ]
#     }
# )

# result = app.invoke(
#     {
#         "messages": [
#             {
#                 "role": "user",
#                 "content": "What's the weather in Chennai",
#             }
#         ]
#     }
# )

# result = asyncio.run(
#     app.ainvoke(
#         {
#             "messages": [
#                 {
#                     "role": "user",
#                     "content": "What's the weather in Chennai and multiply that by 2 and add 100",
#                 }
#             ]
#         }
#     )
# )

result = asyncio.run(
    app.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Search the web for the latest Tata Motors EV launch and summarise it. Also tell me the current weather in Pune",
                }
            ]
        }
    )
)

print(result["messages"][-1].content)
