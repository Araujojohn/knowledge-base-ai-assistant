from unittest.mock import patch, AsyncMock, Mock
import pytest
from rag import rag_pipeline
import rag
import psycopg
from tools import search


@pytest.mark.asyncio
async def test_rag_pipeline_and_search_tool_chunk_retrieval(test_db, monkeypatch):
    """
    Integration test: run the whole RAG pipeline against an empty TEST database,
    then check that the agent's search tool retrieves the right chunk back.
    """

    # GitHub stub: returns one file in the shape the pipeline expects.
    # The content stays in Portuguese on purpose - the real vault is Portuguese,
    # so this keeps the retrieval test faithful to production content.
    def fake_initial_github_pull():

        test_files = {
            "teste.md": {
                "sha": "testsha123",
                "url": "testurl",
                "content": """# Documento de Teste RAG
               Este é um arquivo de teste usado pelo pipeline de sincronização do RAG. Ele existe só para validar chunking, embedding e busca híbrida.
               A palavra-chave secreta deste teste é "abacaxi-quantico". Se a busca encontrar esse chunk, o mecanismo de retrieval está funcionando.""",
            }
        }

        test_sha_novo = "fakesha123"

        return test_files, test_sha_novo

    monkeypatch.setattr(rag, "initial_github_pull", fake_initial_github_pull)

    response = rag_pipeline()
    # 1. did rag_pipeline run end to end?
    assert response == "Sync successful"

    conn = test_db
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM knowledge_base_ai.files
        """
    )

    data = cur.fetchall()
    conn.commit()

    # 2. did the database get populated with the test file?
    assert data != []

    search_tool_result = await search.ainvoke(
        {"query": "Qual é a Palavra Chave Secreta do Arquivo de Teste?"}
    )

    # 3. call the search tool and check the secret keyword came back in the chunks
    assert any("abacaxi-quantico" in chunk[1] for chunk in search_tool_result)
