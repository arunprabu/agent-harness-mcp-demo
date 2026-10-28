# let's have a simple agent with human-in-the-loop review or revision
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI  # uv add langchain-openai python-dotenv
from dotenv import load_dotenv

load_dotenv()

llm = ChatOpenAI(model="gpt-6.1-sol")


# state
class AgentState(TypedDict):
    query: str
    draft_answer: str
    is_approved: bool
    review_comments: str
    final_answer: str


def draft_node(state: AgentState):
    "Creating Draft Answer"
    response = llm.invoke(f"""Answer the following question concisely:
      {state['query']}
    """)

    return {**state, "draft_answer": response.content}


def human_review_node(state: AgentState):
    """Simuating human approval
    (In Real Apps: UI / API / CLI interrupt)
    """
    print(f"=======Review this Answer: {state['draft_answer']}========")

    # Let's collect input from human
    reviewer_input = input("Approve? (yes/no): ").strip().lower()
    is_approved = reviewer_input == "yes"

    if reviewer_input == "no":
        review_comments = input("Review Comments: ").strip().lower()
        return {**state, "is_approved": is_approved, "review_comments": review_comments}

    return {**state, "is_approved": is_approved}


def finalize_node(state: AgentState):
    "Finalize Approved Answer"
    print("==========Approved! Sending Answer===========")

    return {**state, "final_answer": state["draft_answer"]}


def revise_node(state: AgentState):
    "Revise answer if human reviewer says no"
    print("============Revising Answer==============")

    response = llm.invoke(f"""Revise the draft answer for the query:
          {state['query']} 

          Here's the draft answer: {state['draft_answer']}

            based on the following review comments: {state['review_comments']}
        """)

    return {**state, "draft_answer": response.content}


def review_route(state: AgentState):
    if state["is_approved"]:
        return "FINALIZE"

    return "REVISE"


# build the graph
workflow = StateGraph(AgentState)
workflow.add_node("draft", draft_node)
workflow.add_node("review", human_review_node)
workflow.add_node("finalize", finalize_node)
workflow.add_node("revise", revise_node)

workflow.add_edge(START, "draft")
workflow.add_edge("draft", "review")

workflow.add_conditional_edges(
    "review", review_route, {"FINALIZE": "finalize", "REVISE": "revise"}
)

# loop until approved
workflow.add_edge("revise", "review")
workflow.add_edge("finalize", END)

app = workflow.compile()

# generating and saving the graph visualization
graph_image = app.get_graph().draw_mermaid_png()
with open("src/ex7_hitl.png", "wb") as f:
    f.write(graph_image)


result = app.invoke(
    {
        "query": "Explain Langgraph in simpler terms",
        "draft_answer": "",
        "is_approved": False,
        "final_answer": "",
    }
)

print("Final Answer: ", result["final_answer"])
