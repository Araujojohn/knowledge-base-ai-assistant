import pytest
import pytest_asyncio
from nodes import agent_node
from unittest.mock import patch, AsyncMock
from langchain_core.messages import AIMessage


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
