from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from langchain_openai import ChatOpenAI  # uv add langchain-openai python-dotenv
from dotenv import load_dotenv

load_dotenv()

# initialize the LLM
llm = ChatOpenAI(model="gpt-6.1-sol")


# 1. custom state
class AgentState(TypedDict):
    query: str
    decision: str
    response: str


def prompt_review_node(state: AgentState):
    """LLM decides whether the query is clear or not"""
    query = state["query"]

    prompt = f"""
        You are a prompt reviewer. Classify the user query as: 
        - CLEAR
        - UNCLEAR
        Query: {query}

        Respond with only one word: CLEAR or UNCLEAR
    """

    decision = llm.invoke(prompt).content

    return {"decision": decision}


def answer_node(state: AgentState):
    """will connect to LLM to get an answer"""
    prompt = f"""
       Answer the following question clearly and concisely
    
        {state["query"]}
    """
    answer = llm.invoke(prompt).content

    return {"response": answer}


def clarify_node(state: AgentState):
    return {"response": f"Can you clearify your query: {state["query"]} "}


def route(state: AgentState):
    return state["decision"]


# 2. building graph
workflow = StateGraph(AgentState)

# will return "CLEAR" or "UNCLEAR"
workflow.add_node("prompt_review", prompt_review_node)
workflow.add_node("answer", answer_node)
workflow.add_node("clarify", clarify_node)

workflow.add_edge(START, "prompt_review")

workflow.add_conditional_edges(
    "prompt_review", route, {"CLEAR": "answer", "UNCLEAR": "clarify"}
)

workflow.add_edge("answer", END)
workflow.add_edge("clarify", END)

app = workflow.compile()

# generating and saving the graph visualization
graph_image = app.get_graph().draw_mermaid_png()
with open("src/ex5_research_clarify_answer.png", "wb") as f:
    f.write(graph_image)

result = app.invoke({"query": "Explain quantum computing in simple terms"})
print(result)
