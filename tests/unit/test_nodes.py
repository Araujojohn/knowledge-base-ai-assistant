import pytest
import pytest_asyncio
import logging
from nodes import agent_node, safe_message_window
import sentinel_erros
from unittest.mock import patch, AsyncMock, Mock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# response-shape test
@pytest.mark.asyncio
@patch("nodes.check_if_model_changed")
async def test_agent_node_returns_a_correctly_shaped_response(
    mock_check_if_model_changed,
):
    mock_model = AsyncMock()
    mock_model.ainvoke.return_value = AIMessage(
        content="correctly shaped test response"
    )
    mock_check_if_model_changed.return_value = mock_model

    message = {"messages": [("human", "hi")]}

    result = await agent_node(message)

    assert result == {"messages": [AIMessage(content="correctly shaped test response")]}


# error-fallback test
@pytest.mark.asyncio
@patch("nodes.check_if_model_changed")
async def test_agent_node_returns_the_fallback_response_on_error(
    mock_check_if_model_changed,
):
    mock_model = AsyncMock()
    mock_model.ainvoke.side_effect = Exception("simulated failure")
    mock_check_if_model_changed.return_value = mock_model

    message = {"messages": [("human", "hi")]}

    result = await agent_node(message)

    assert result == {
        "messages": [
            AIMessage(
                content="Sorry, I hit an internal error while processing your request. Please try again."
            )
        ]
    }


# The model failing must reach someone, not only the user. LEARNINGS: the Anthropic credit ran out
# and the user got "internal error" for days while nobody knew (prod down since 22/10).
@pytest.mark.asyncio
@patch("nodes.check_if_model_changed")
async def test_a_model_failure_reaches_the_sentinel(mock_check_if_model_changed):
    mock_model = AsyncMock()
    mock_model.ainvoke.side_effect = Exception("credit balance is too low")
    mock_check_if_model_changed.return_value = mock_model
    handler = sentinel_erros.SentinelHandler("test-token", url="http://sentinel.invalid")
    handler.sender.submit = Mock()
    logging.getLogger().addHandler(handler)
    try:
        await agent_node({"messages": [("human", "hi")]})
    finally:
        logging.getLogger().removeHandler(handler)

    where, exc = handler.sender.submit.call_args.args[1:3]
    assert where == "nodes:agent_node"
    assert "credit balance is too low" in str(exc)


# A blind cut by count can open the window on an AIMessage with tool_calls (or its ToolMessage),
# with no user turn before it: Gemini rejects that request (nodes.py, safe_message_window).
def tool_round(call_id):
    return [
        AIMessage(content="", tool_calls=[{"name": "search", "args": {"query": "x"}, "id": call_id}]),
        ToolMessage(content="result", tool_call_id=call_id),
    ]


def test_safe_message_window_never_opens_inside_a_tool_call():
    messages = [
        HumanMessage("first question"), *tool_round("a"), AIMessage("first answer"),
        HumanMessage("second question"), *tool_round("b"), AIMessage("second answer"),
    ]

    window = safe_message_window(messages, n=3)

    assert window == messages[4:]
    assert isinstance(window[0], HumanMessage)


def test_safe_message_window_keeps_a_short_history_whole():
    messages = [HumanMessage("question"), *tool_round("a"), AIMessage("answer")]

    assert safe_message_window(messages, n=30) == messages
