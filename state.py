from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
from typing import TypedDict, Annotated



class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages()]





