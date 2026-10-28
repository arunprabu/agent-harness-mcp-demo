"""
common.py — shared pieces used by every demo.

1. Tools      : calculator, live weather (Open-Meteo), time, web search (Tavily).
2. get_llm()  : the agent's brain — a real chat model (set OPENAI_API_KEY in .env).
3. Helpers    : banner() for headings, save_graph_png() for graph diagrams.

"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

load_dotenv()  # API keys from .env (copy .env.example)


# ════════════════════════════════════════════════════════════════════
# 1. TOOLS
# ════════════════════════════════════════════════════════════════════


@tool
def calculator(expression: str):
    """Evaluate Math expression. For all your calculations you must use this function"""
    print("Calling calculator_tool")
    try:
        # this is dangerous but we trust the input for the demo (do NOT use eval on untrusted input)
        return str(eval(expression))
    except:
        return "Error in Calculation"


@tool
def get_weather(latitude: str, longitude: str):
    """
    use this tool to get weather info for a valid city
    """
    print("Geocoordinates :" + latitude + " and  " + longitude)

    weather_api_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
    weather_output = requests.get(weather_api_url)
    current_weather = weather_output.json()
    return current_weather


@tool
def get_time(timezone: str = "Asia/Kolkata") -> str:
    """Get the current date and time in an IANA timezone (default India)."""
    now = datetime.now(ZoneInfo(timezone))
    return f"Current time in {timezone}: {now:%Y-%m-%d %H:%M}"


@tool
def web_search(query: str) -> str:
    """Search the web for recent or factual information."""
    if os.getenv("TAVILY_API_KEY"):
        from langchain_tavily import TavilySearch

        res = TavilySearch(max_results=3).invoke({"query": query})
        rows = res.get("results", []) if isinstance(res, dict) else []
        return (
            "\n".join(
                f"- {r['title']}: {r['content'][:200]} ({r['url']})" for r in rows
            )
            or "No results"
        )


ALL_TOOLS = [calculator, get_weather, get_time, web_search]


# ════════════════════════════════════════════════════════════════════
# 2. THE LLM
# ════════════════════════════════════════════════════════════════════


def get_llm():
    """The agent's brain: a real chat model (default openai:gpt-6.1-sol).

    MODEL switches provider, in LangChain's 'provider:model' format, e.g.
      openai:gpt-6.1-mini   anthropic:claude-haiku-4-5   google_genai:gemini-2.5-flash
    """
    if os.getenv("OPENAI_API_KEY") or os.getenv("MODEL"):
        model = os.getenv("MODEL", "openai:gpt-4o-mini")
        print(f"🔌 Using real LLM: {model}")
        return init_chat_model(model)


# ════════════════════════════════════════════════════════════════════
# 3. HELPERS
# ════════════════════════════════════════════════════════════════════


def banner(title):
    print("\n" + "═" * 70 + f"\n  {title}\n" + "═" * 70)


def save_graph_png(graph, filename):
    """Save the graph's Mermaid diagram as a PNG in diagrams/ so you can SEE the flow.

    draw_mermaid_png() renders through the mermaid.ink web service, so it needs
    internet. Offline, we save the Mermaid text (.mmd) instead — paste it into
    https://mermaid.live to see it drawn.
    """
    out = Path(__file__).parent / "diagrams" / filename
    out.parent.mkdir(exist_ok=True)
    try:
        graph_image = graph.get_graph().draw_mermaid_png()
        with open(out, "wb") as f:
            f.write(graph_image)
        print(f"🖼️  Graph diagram saved to diagrams/{out.name}")
    except Exception as e:  # offline or service down → fall back to Mermaid text
        out = out.with_suffix(".mmd")
        out.write_text(graph.get_graph().draw_mermaid())
        print(
            f"🖼️  Couldn't render PNG ({type(e).__name__}); Mermaid text saved to "
            f"diagrams/{out.name} — paste it into https://mermaid.live"
        )


__all__ = [
    "calculator",
    "get_weather",
    "get_time",
    "web_search",
    "ALL_TOOLS",
    "get_llm",
    "banner",
    "save_graph_png",
    "AIMessage",
    "HumanMessage",
    "SystemMessage",
    "ToolMessage",
]
