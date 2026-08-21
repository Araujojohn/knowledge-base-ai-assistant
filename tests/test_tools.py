from tools import read, list_files, write
from unittest.mock import patch, AsyncMock, Mock
import pytest
import httpx


@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_updates_file_correctly_when_sha_is_provided(
    mocked_client_get, mocked_client_put
):

    mocked_client_get.return_value = Mock()

    mocked_client_put.return_value = Mock()

    mocked_client_get.return_value.json.return_value = {"sha": 123}
    mocked_client_put.return_value.json.return_value = {
        "content": {"path": "test_file.md"}
    }

    result = await write.ainvoke(
        {
            "path": "test_file.md",
            "content": "content for the update path",
            "commit_message": "update existing file",
        }
    )
    assert result == "test_file.md"
    assert mocked_client_put.call_args.kwargs["json"]["sha"] == "123"


@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_creates_new_file_correctly_when_no_sha_is_provided(
    mocked_client_get, mocked_client_put
):

    request = Mock()
    response = Mock(status_code=404)

    mocked_client_get.return_value = Mock()
    mocked_client_put.return_value = Mock()
    mocked_client_get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "any message", request=request, response=response
    )
    mocked_client_put.return_value.json.return_value = {
        "content": {"path": "test_file.md"}
    }

    result = await write.ainvoke(
        {
            "path": "test_file.md",
            "content": "content for the create path",
            "commit_message": "create new file",
        }
    )
    assert result == "test_file.md"
    assert mocked_client_put.call_args.kwargs["json"]["message"] == "create new file"
