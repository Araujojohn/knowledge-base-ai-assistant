import os

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from nodes import agent_node
from state import AgentState
from tools import tools

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")


def check_tool_call(state: AgentState):
    last_message = state["messages"][-1]
    if last_message.tool_calls != []:
        result = "tools"
    else:
        result = END
    return result


# Builds the graph map and compiles it
builder = StateGraph(AgentState)
builder.set_entry_point("AI_Agent")
builder.add_node("AI_Agent", agent_node)
builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
builder.add_conditional_edges("AI_Agent", check_tool_call)
builder.add_edge("tools", "AI_Agent")
graph = builder.compile(checkpointer=InMemorySaver())


## Sends a message to the agent and streams the response back, unpacked into
## clearly typed chunks (thinking, tool_use or final text).
async def send_message_to_ai(message: str, thread_id):
    try:
        async for event in graph.astream(
            input={"messages": [message]},
            stream_mode="updates",
            config={
                "recursion_limit": 30,
                "configurable": {"thread_id": f"{thread_id}"},
            },
        ):
            for aimessage in event.values():
                for msg in aimessage["messages"]:
                    if msg.type == "ai":
                        is_final = not msg.tool_calls
                        for block in msg.content_blocks:
                            if block["type"] == "text" and is_final:
                                print(
                                    {
                                        "Type": "final_answer",
                                        "content": f"{block['text']}",
                                    }
                                )
                                yield {
                                    "Type": "final_answer",
                                    "content": f"{block['text']}",
                                }
                            elif block["type"] == "reasoning":
                                print({"Type": "thinking", "content": "Thinking..."})
                                yield {"Type": "thinking", "content": "Thinking..."}
                            elif block["type"] == "tool_call":
                                print(f"{block['name']} {block['args']}\n")
                                yield {
                                    "Type": "tool_use",
                                    "content": f"{block['name']} {block['args']}",
                                }
    except GraphRecursionError:
        print(
            {
                "Type": "error",
                "content": "Reached the retry limit. Want to try a different angle?\n",
            }
        )
        yield {
            "Type": "error",
            "content": "Reached the retry limit. Want to try a different angle?",
        }
