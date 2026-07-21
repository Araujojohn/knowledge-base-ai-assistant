from tools import read, list_files, write
from unittest.mock import patch, AsyncMock, Mock
import pytest
import httpx


@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_updates_file_correctly_when_sha_is_provided(mocked_client_get, mocked_client_put):
    
    mocked_client_get.return_value = Mock()

    mocked_client_put.return_value = Mock()

    mocked_client_get.return_value.json.return_value = {"sha": 123}
    mocked_client_put.return_value.json.return_value = {"content": {"path": "arquivo_teste.md"}}
    

    result = await write.ainvoke({"path": "arquivo_teste.md", "content": "teste fazendo update arquivo", "commit_message": "novo arquivo atualizado"})
    assert result == "arquivo_teste.md"
    assert mocked_client_put.call_args.kwargs["json"]["sha"] == "123"
    




@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_creates_new_file_correctly_when__no_sha_is_provided(mocked_client_get, mocked_client_put):
    

    request = Mock()
    response= Mock(status_code=404)

    mocked_client_get.return_value = Mock()
    mocked_client_put.return_value = Mock()
    mocked_client_get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError("mensagem qualquer", request=request, response=response)
    mocked_client_put.return_value.json.return_value = {"content": {"path": "arquivo_teste.md"}}
    

    result = await write.ainvoke({"path": "arquivo_teste.md", "content": "teste criando arquivo", "commit_message": "novo arquivo criado"})
    assert result == "arquivo_teste.md"
    assert mocked_client_put.call_args.kwargs["json"]["message"] == "novo arquivo criado"