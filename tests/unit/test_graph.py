import logging
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
import sentinel_erros
from graph import check_tool_call, send_message_to_ai
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


def model_answering(*responses):
    """A fake model that hands out the given responses in order (callables are called each turn)."""
    turns = iter(responses)
    model = AsyncMock()
    model.ainvoke.side_effect = lambda messages: (lambda r: r() if callable(r) else r)(next(turns))
    return model


def endless_tool_call():
    return AIMessage(content="", tool_calls=[{"name": "no_such_tool", "args": {}, "id": str(uuid.uuid4())}])


# graph.py: a model that never stops calling tools hits recursion_limit; the user must still get an
# answer instead of silence.
@pytest.mark.asyncio
@patch("nodes.check_if_model_changed")
async def test_hitting_the_recursion_limit_still_answers_the_user(mock_check_if_model_changed):
    mock_check_if_model_changed.return_value = model_answering(*[endless_tool_call] * 100)

    events = [event async for event in send_message_to_ai("loop forever", "test-recursion-limit")]

    assert events[-1] == {
        "type": "error",
        "content": "Reached the retry limit. Want to try a different angle?",
    }


# LEARNINGS: the OpenAI key had no credit, `search` failed on every call and the agent kept browsing
# file by file for days. Every paid dependency needs an error that reaches someone.
@pytest.mark.xfail(
    strict=True,
    reason="open gap: ToolNode(handle_tool_errors=True) turns the exception into a message for the "
    "model and logs nothing, so the Sentinel never hears about a failing search",
)
@pytest.mark.asyncio
@patch("tools.get_db_connection", side_effect=RuntimeError("insufficient_quota"))
@patch("nodes.check_if_model_changed")
async def test_a_search_failure_reaches_the_sentinel(mock_check_if_model_changed, _db):
    search_call = AIMessage(
        content="", tool_calls=[{"name": "search", "args": {"query": "x"}, "id": "1"}]
    )
    mock_check_if_model_changed.return_value = model_answering(search_call, AIMessage("done"))
    handler = sentinel_erros.SentinelHandler("test-token", url="http://sentinel.invalid")
    handler.sender.submit = Mock()
    logging.getLogger().addHandler(handler)
    try:
        events = [event async for event in send_message_to_ai("search it", "test-search-failure")]
    finally:
        logging.getLogger().removeHandler(handler)

    assert events[-1]["type"] == "final_answer"
    assert handler.sender.submit.called
