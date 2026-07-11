from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from state import AgentState
from tools import tools
import os
from dotenv import load_dotenv

load_dotenv()


model = ChatAnthropic(model="claude-sonnet-5").bind_tools(tools)

system_prompt = f"""
CONTEXT
You are a General assistant with access to the user Knowledge base 
(Context Stored in Github as .md files)"

OBJECTIVE
your goal is to use the knowledge base context to provide personalized
assistance to the user needs

REFERENCES
user: {os.getenv("GITHUB_OWNER")}
repo: {os.getenv("GITHUB_REPO")}

Obs: The CLAUDE.md file its the map of the repo, and index

Rules:
1° Clarity in Comunnication: try to say what matters in a brief way with as fewer words as possible while maintaining effectively communication, reduce what's unecessary to say
"""

async def agent_node(state: AgentState):
    mensagens = [("system", system_prompt)] + state["messages"]
    try:
     response = await model.ainvoke(mensagens)
    except Exception as error:
     response = AIMessage(content="Desculpa, tive um erro interno ao processar sua solicitação, tente novamente por favor.")
    return {"messages": [response]}

