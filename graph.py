from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.errors import GraphRecursionError
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
import os
from state import AgentState
from nodes import agent_node
from tools import tools
import json


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
                        if isinstance(msg.content, str):
                            print({"Type": "final_answer", "content": f"{msg.content}"})
                            yield {"Type": "final_answer", "content": f"{msg.content}"}
                        else:
                            for item in msg.content:
                                if item["type"] == "text":
                                    print(
                                        {
                                            "Type": "final_answer",
                                            "content": f"{item['text']}",
                                        }
                                    )
                                    yield {
                                        "Type": "final_answer",
                                        "content": f"{item['text']}",
                                    }
                                elif item["type"] == "thinking":
                                    print(
                                        {"Type": "thinking", "content": "Thinking..."}
                                    )
                                    yield {"Type": "thinking", "content": "Thinking..."}
                                elif item["type"] == "tool_use":
                                    print(f"{item['name']} {item['input']}\n")
                                    yield {
                                        "Type": "tool_use",
                                        "content": f"{item['name']} {item['input']}",
                                    }
    except GraphRecursionError as error:
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
