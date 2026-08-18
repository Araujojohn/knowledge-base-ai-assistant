from langchain_anthropic import ChatAnthropic
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from state import AgentState
from tools import tools
import os
import time
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

def check_if_model_changed():
    """Checa a cada 5min, se o modelo de IA foi trocado no Banco"""
    last_search = cache["checked_at"]
    seconds_passed = time.time() - last_search
    if seconds_passed > 300:
       conn = connect_to_database()
       configs = check_ai_configs(conn)
       conn.close()
       cache["model"] = init_chat_model(configs).bind_tools(tools)
       cache["checked_at"] = time.time()
    return cache["model"]



system_prompt = prompts.agent_node_system_prompt

async def agent_node(state: AgentState):
    mensagens = [("system", system_prompt)] + state["messages"][-30:]
    model = check_if_model_changed()
    try:
     response = await model.ainvoke(mensagens)
    except Exception as error:
     response = AIMessage(content="Desculpa, tive um erro interno ao processar sua solicitação, tente novamente por favor.")
    return {"messages": [response]}

