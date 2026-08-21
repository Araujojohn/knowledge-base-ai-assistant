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
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT"),
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
    """Re-read the model config from the database at most once every 5 minutes."""
    last_search = cache["checked_at"]
    seconds_passed = time.time() - last_search
    if seconds_passed > 300:
        configs = await asyncio.to_thread(fetch_model_config)
        cache["model"] = init_chat_model(configs).bind_tools(tools)
        cache["checked_at"] = time.time()
    return cache["model"]


system_prompt = prompts.agent_node_system_prompt


def safe_message_window(messages, n=30):
    """Return the last n messages, never cutting inside a tool-call/tool-response pair.

    A blind cut by count can leave an AIMessage carrying tool_calls as the first
    message of the window, with no preceding user turn (or tool result) for it to
    answer to. Anthropic tolerates that; Gemini rejects it. Walking back to the
    last HumanMessage guarantees a cut point that is valid for any provider.
    """
    start = max(0, len(messages) - n)
    while start > 0 and not isinstance(messages[start], HumanMessage):
        start -= 1
    return messages[start:]


async def agent_node(state: AgentState):
    messages = [("system", system_prompt)] + safe_message_window(state["messages"])
    model = await check_if_model_changed()
    try:
        response = await model.ainvoke(messages)
    except Exception as error:
        print(f"agent_node model.ainvoke failed: {error!r}")
        traceback.print_exc()
        response = AIMessage(
            content="Sorry, I hit an internal error while processing your request. Please try again."
        )
    return {"messages": [response]}
