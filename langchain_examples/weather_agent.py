from langchain.agents import create_agent
from langchain.tools import tool
from dotenv import load_dotenv
from langchain.mcp import MCPAdapter
import requests
import asyncio

# load the env variables
load_dotenv()


# what's a tool?
# Tool is a function that the agent can call
# tool must have a name and description
# tool must return data
# tool can have parameter
# tool must be called by your agent
# tool in langchain must have @tool decorator


# @tool
# def get_weather(latitude: str, longitude: str):
#     """
#     use this tool to get weather info for a valid city
#     """
#     print("Geocoordinates :" + latitude + " and  " + longitude)

#     weather_api_url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
#     weather_output = requests.get(weather_api_url)
#     current_weather = weather_output.json()
#     return current_weather

MY_MCP_URL = "http://127.0.0.1:8100/mcp"


async def main():
    async with MCPAdapter(MY_MCP_URL) as adapter:
        tools = await adapter.list_tools()
        weather_agent = create_agent(
            model="openai:gpt-6-sol",  # brain of the agent
            tools=tools,  # registering the tools (list_tools() already returns a list)
            system_prompt="""You are an AI assistant. 
            You are given access to many tools. 
            For ex: if the city is invalid or fictional for a weather tool, 
            respond to the user 'Invalid or Fictional City' before the calling the tool""",
        )

        # user's message (MCP tools are async-only, so use ainvoke)
        response = await weather_agent.ainvoke(
            {"messages": [{"role": "user", "content": "what's the weather in London"}]}
        )

        print(response["messages"][-1].text)

        # let's print the token usage
        print(response["messages"][-1].usage_metadata)


if __name__ == "__main__":
    asyncio.run(main())
