import pytest
from graph import check_tool_call
from state import AgentState
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage
from langchain_core.messages import AIMessage

state_with_tools = {
    "messages": [
        AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": "algum.md"}, "id": "1"}],
        )
    ]
}


state_without_tools = {"messages": [AIMessage(content="oi", tool_calls=[])]}


def test_check_tool_call_returns_tools_when_the_message_has_a_tool_call():
    result = check_tool_call(state_with_tools)
    assert result == "tools"


def test_check_tool_call_returns_end_when_the_message_has_no_tool_call():
    result = check_tool_call(state_without_tools)
    assert result == END
