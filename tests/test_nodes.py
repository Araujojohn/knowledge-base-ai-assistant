import pytest
import pytest_asyncio
from nodes import agent_node
from unittest.mock import patch, AsyncMock
from langchain_core.messages import AIMessage

#teste de formato de resposta 
@pytest.mark.asyncio
@patch("nodes.model", new_callable=AsyncMock)
async def test_agent_node_retorna_resposta_no_formato_correto(mock_model):
  mock_model.ainvoke.return_value = AIMessage(content="resposta de teste no formato correto")

  mensagem = {"messages": [("human", "oi")]}

  resultado = await agent_node(mensagem)

  assert resultado == {"messages":[AIMessage(content="resposta de teste no formato correto")]}



#teste de fallback erro 
@pytest.mark.asyncio
@patch("nodes.model", new_callable=AsyncMock)
async def test_agent_node_retorna_resposta_fallback(mock_model):
  mock_model.ainvoke.side_effect = Exception("erro simulado")

  mensagem = {"messages": [("human", "oi")]}

  resultado = await agent_node(mensagem)

  assert resultado == {"messages":[AIMessage(content="Desculpa, tive um erro interno ao processar sua solicitação, tente novamente por favor.")]}


