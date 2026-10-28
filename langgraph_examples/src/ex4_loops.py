from langgraph.graph import StateGraph, START, END
from typing import TypedDict


# 1 custom state
class NumberState(TypedDict):
    number: int  # 10
    is_valid: bool
    attempts: int


def validate_node(state: NumberState):
    """Will check whether the number is positive or negative"""
    is_valid = state["number"] > 0

    return {"is_valid": is_valid, "attempts": state["attempts"] + 1}


def retry_node(state: NumberState):
    """Simulate rety (fixing the input which is number)"""
    new_number = state["number"] + 5
    return {"number": new_number}


def route(state: NumberState):
    if state["is_valid"]:
        return "SUCCESS"

    return "RETRY"


def success_node(state: NumberState):
    """Final Response"""
    print("Valid number Found!")
    return state


workflow = StateGraph(NumberState)
workflow.add_node("validate", validate_node)
workflow.add_node("retry", retry_node)
workflow.add_node("success", success_node)

workflow.add_edge(START, "validate")
workflow.add_conditional_edges(
    "validate", route, {"SUCCESS": "success", "RETRY": "retry"}
)

# this is the important one.. making retry as loop
workflow.add_edge("retry", "validate")
workflow.add_edge("success", END)

app = workflow.compile()

# generating and saving the graph visualization
graph_image = app.get_graph().draw_mermaid_png()
with open("src/ex4_loops.png", "wb") as f:
    f.write(graph_image)

result = app.invoke({"number": -6, "attempts": 0})
print(result)
