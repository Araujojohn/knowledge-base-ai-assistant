from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from state import AgentState
from tools import tools
import os
from dotenv import load_dotenv
import prompts

load_dotenv()


model = ChatAnthropic(model="claude-sonnet-5").bind_tools(tools)

system_prompt = prompts.agent_node_system_prompt

async def agent_node(state: AgentState):
    mensagens = [("system", system_prompt)] + state["messages"]
    try:
     response = await model.ainvoke(mensagens)
    except Exception as error:
     response = AIMessage(content="Desculpa, tive um erro interno ao processar sua solicitação, tente novamente por favor.")
    return {"messages": [response]}

