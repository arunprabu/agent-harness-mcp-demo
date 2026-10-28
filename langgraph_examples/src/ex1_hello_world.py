# uv add langgraph
from langgraph.graph import StateGraph, MessagesState, START, END


def mock_llm(state: MessagesState):
    print("Mock LLM called")
    print(state)
    return {"messages": [{"role": "ai", "content": "Hello World!"}]}


# define the graph
# our graph will deal with messages, so we use MessagesState as the state type
graph = StateGraph(MessagesState)


graph.add_node("mock_llm_node", mock_llm)
graph.add_edge(START, "mock_llm_node")
graph.add_edge("mock_llm_node", END)
workflow = graph.compile()

graph_image = workflow.get_graph().draw_mermaid_png()
with open("src/ex1_hello_world.png", "wb") as f:
    f.write(graph_image)

result = workflow.invoke({"messages": [{"role": "user", "content": "Hey!"}]})
print("*" * 50)

print(result)

# How to execute this?
# python src/ex1_hello_world.py
