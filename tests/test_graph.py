import pytest
from graph import check_tool_call
from state import AgentState
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage
from langchain_core.messages import AIMessage

state_com_tools = {
    "messages": [
        AIMessage(content="", tool_calls=[
            {"name": "read", "args": {"path": "algum.md"}, "id": "1"}
        ])
    ]
}


state_sem_tools = {
     "messages": [
         AIMessage(content="oi", tool_calls=[])]}



def test_check_tool_call_retorna_string_tools_quando_existe_tool_na_mensagem():
 resultado = check_tool_call(state_com_tools)
 assert resultado == "tools"

def test_check_tool_call_retorna_END_quando_sem_tool_call_na_mensagem():
 resultado = check_tool_call(state_sem_tools)
 assert resultado == END