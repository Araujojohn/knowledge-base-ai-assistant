from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from fastapi.responses import StreamingResponse
import langgraph.errors
from dotenv import load_dotenv
import os
from state import AgentState
from nodes import agent_node
from tools import tools
import json


load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

STEP_SEP = "\n<<<MSG_BREAK>>>\n"

def check_tool_call(state: AgentState):
    ultima_mensagem = state["messages"][-1]
    if ultima_mensagem.tool_calls != []:
     resultado = "tools"
    else:
     resultado = END
    return resultado

#Builds the graph map and compiles it
builder = StateGraph(AgentState)
builder.set_entry_point("AI_Agent")
builder.add_node("AI_Agent", agent_node)
builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
builder.add_conditional_edges("AI_Agent", check_tool_call)
builder.add_edge("tools", "AI_Agent")
graph = builder.compile()

##Send Message to AI, and Unpack/Format Reponse in a clear, stream (thinking, tool_use or text repsonse)
def send_message_to_ai(message: str):
 async def unpack_response():
  try:
   async for event in graph.astream(
    input={"messages": [message]
    },
    stream_mode="updates",
    config={"recursion_limit": 15}
    ):
    for aimessage in event.values():
     for msg in aimessage["messages"]:
      if msg.type == "ai":
       if isinstance(msg.content, str):
        print(msg.content)
        yield f"{msg.content}{STEP_SEP}"
       else:
        for item in msg.content:
         if item["type"] == "text":
          print(item["text"])
          yield f"{item["text"]}{STEP_SEP}"
         elif item["type"] == "thinking":
          print("Pensando...\n")
          yield f"Pensando...{STEP_SEP}"
         elif item["type"] == "tool_use":
          print(f"[{item["name"]}]: [{item["input"]["path"]}]\n")
          yield f"[{item["name"]}]: [{item["input"]["path"]}]{STEP_SEP}"
  except GraphRecursionError as erro:
   print("Antingi o Limite de tentativas, quer tentar por um outro caminho?\n")
   yield f"Antingi o Limite de tentativas, quer tentar por um outro caminho?{STEP_SEP}"
 return StreamingResponse(unpack_response())

