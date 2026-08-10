from unittest.mock import patch, AsyncMock, Mock
import pytest
from rag import rag_pipeline
import rag
import psycopg
from tools import search

@pytest.mark.asyncio
async def test_rag_pipeline_and_search_tool_chunk_retrieval(test_DB, monkeypatch):
    """
    Integration test, test the complete rag pipeline 
    running on a empty TEST database, and tests the doc/chunk retrieval of the agent 
    """

    #Github Mock, traz um arquivo no formato que o pipeline espera, 
    def fake_initial_github_pull():
        
   
        test_files = {
            "teste.md": {
               "sha": "testsha123", "url": "testurl", "content": 
               """# Documento de Teste RAG
               Este é um arquivo de teste usado pelo pipeline de sincronização do RAG. Ele existe só para validar chunking, embedding e busca híbrida.
               A palavra-chave secreta deste teste é "abacaxi-quantico". Se a busca encontrar esse chunk, o mecanismo de retrieval está funcionando."""
            }
         }
            
        test_sha_novo = "fakesha123"

        return test_files, test_sha_novo
        
    monkeypatch.setattr(rag, "initial_github_pull", fake_initial_github_pull)
    
    response = rag_pipeline()
    #1 checa se a função rag_pipeline rodou de ponta a ponta
    assert response == "Sucesso no Sync"
   
    conn = test_DB
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM knowledge_base_ai.files
        """
      )

    data = cur.fetchall()
    conn.commit()

    #2 checa se banco foi populado com o arquivo de teste
    assert data != []

    Search_tool_result = await search.ainvoke({"query": "Qual é a Palavra Chave Secreta do Arquivo de Teste?"})

    #3 Chama tool "Search" e compara se nos resultados(Chunks) tem a palavra chave
    assert any("abacaxi-quantico" in chunk[1] for chunk in Search_tool_result)