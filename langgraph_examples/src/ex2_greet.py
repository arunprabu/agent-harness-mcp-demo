# greet example is using langgraph with custom state
from langgraph.graph import StateGraph, START, END
from typing import TypedDict


# 1. defining custom state
class SimpleState(TypedDict):
    user_name: str
    message: str
    status: str


def greet(state: SimpleState):
    print("\n ================== 1. GREET NODE =========")
    print("State Received:", state)  # current state

    # Update the state
    my_message = "Hello, " + state["user_name"]
    return {"message": my_message}


def status(state: SimpleState):
    print("\n ================== 2. STATUS NODE =========")
    print("State Received:", state)  # current state

    # Update the state
    my_status = "Workflow Completed for the user " + state["user_name"]
    return {"status": my_status}


# 2. defining the graph
graph = StateGraph(SimpleState)

graph.add_node("greet_node", greet)
graph.add_node("status_node", status)

graph.add_edge(START, "greet_node")
graph.add_edge("greet_node", "status_node")
graph.add_edge("status_node", END)

workflow = graph.compile()

# generating and saving the graph visualization
graph_image = workflow.get_graph().draw_mermaid_png()
with open("src/ex2_greet.png", "wb") as f:
    f.write(graph_image)

result = workflow.invoke({"user_name": "Alice"})
print(result)
