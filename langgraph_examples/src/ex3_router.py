from langgraph.graph import StateGraph, START, END
from typing import TypedDict


# 1. defining custom state
class NumberState(TypedDict):
    number: int
    result: str


def check_node(state: NumberState):
    """Decide if the number is even or odd"""
    print("\n ================== 1. CHECK NODE =========")
    print("State Received:", state)  # current state
    print(f"Checking the number: {state['number']}")
    return state


def route(state: NumberState):
    print("\n ================== 2. route NODE =========")
    print("I am router. Will return either the number is even or odd")
    print("State Received:", state)  # current state

    if state["number"] % 2 == 0:
        return "EVEN_NUMBER"

    return "ODD_NUMBER"


def even_node(state: NumberState):
    """updates the result with even number"""
    return {"result": f"{state['number']} is even"}


def odd_node(state: NumberState):
    """updates the result with odd number"""
    return {"result": f"{state['number']} is odd"}


workflow = StateGraph(NumberState)

workflow.add_node("check", check_node)
workflow.add_node("even", even_node)
workflow.add_node("odd", odd_node)

workflow.add_edge(START, "check")

# Making check node as router node
workflow.add_conditional_edges(
    "check",
    route,  # our own routing function
    {"EVEN_NUMBER": "even", "ODD_NUMBER": "odd"},
)

workflow.add_edge("even", END)
workflow.add_edge("odd", END)

app = workflow.compile()


# generating and saving the graph visualization
graph_image = app.get_graph().draw_mermaid_png()
with open("src/ex3_router.png", "wb") as f:
    f.write(graph_image)

result = app.invoke({"number": 5})
print(result)
