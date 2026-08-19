from langchain_anthropic import ChatAnthropic
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage
from state import AgentState
from tools import tools
import os
import time
import asyncio
import traceback
from dotenv import load_dotenv
import prompts
import psycopg

load_dotenv()
def connect_to_database():
    conn = psycopg.connect(
        host = os.getenv("DB_HOST"),
        dbname = os.getenv("DB_NAME"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        port = os.getenv("DB_PORT")
    )
    return conn

def check_ai_configs(conn):
    cur = conn.cursor()
    cur.execute(
        """ 
        SELECT key, value
        FROM knowledge_base_ai.agent_config
        """
    )
   
    configs = cur.fetchone()[1]
    return configs


cache = {"model": None, "checked_at": 0}

def fetch_model_config():
    conn = connect_to_database()
    configs = check_ai_configs(conn)
    conn.close()
    return configs


async def check_if_model_changed():
    """Checa a cada 5min, se o modelo de IA foi trocado no Banco"""
    last_search = cache["checked_at"]
    seconds_passed = time.time() - last_search
    if seconds_passed > 300:
       configs = await asyncio.to_thread(fetch_model_config)
       cache["model"] = init_chat_model(configs).bind_tools(tools)
       cache["checked_at"] = time.time()
    return cache["model"]



system_prompt = prompts.agent_node_system_prompt

def safe_message_window(messages, n=30):
    """Corta as ultimas n mensagens, mas nunca no meio de um par tool-call/tool-response.

    Um corte cego por quantidade pode deixar uma AIMessage com tool_calls como
    primeira mensagem da janela — sem o turno de usuario (ou de resposta de
    tool) que precisa vir antes dela. O Anthropic tolera isso; o Gemini rejeita
    (400 INVALID_ARGUMENT: "function call turn comes immediately after a user
    turn or after a function response turn"). Andar pra tras ate a ultima
    HumanMessage garante um ponto de corte valido pra qualquer provider.
    """
    start = max(0, len(messages) - n)
    while start > 0 and not isinstance(messages[start], HumanMessage):
        start -= 1
    return messages[start:]

async def agent_node(state: AgentState):
    mensagens = [("system", system_prompt)] + safe_message_window(state["messages"])
    model = await check_if_model_changed()
    try:
     response = await model.ainvoke(mensagens)
    except Exception as error:
     print(f"agent_node model.ainvoke failed: {error!r}")
     traceback.print_exc()
     response = AIMessage(content="Desculpa, tive um erro interno ao processar sua solicitação, tente novamente por favor.")
    return {"messages": [response]}

