import pytest
import os
from dotenv import load_dotenv
from rag import db_init
import psycopg


@pytest.fixture
def test_DB(monkeypatch):
    """
    Prepares the DB for the rag_pipeline test, switchs the db conn to Tests Database
    cleans the database, returns a Conn to the Tests Database and closes connection after teststing, 
    """

    #muda env vars pro banco de teste
    monkeypatch.setenv("DB_HOST", os.getenv("DB_HOST"))
    monkeypatch.setenv("DB_PORT", os.getenv("DB_PORT"))
    monkeypatch.setenv("DB_NAME", os.getenv("TESTS_DB_NAME"))
    monkeypatch.setenv("DB_USER", os.getenv("TESTS_DB_USER"))
    monkeypatch.setenv("DB_PASSWORD", os.getenv("TESTS_DB_PASSWORD"))

    conn = psycopg.connect(
        host = os.getenv("DB_HOST"),
        dbname = os.getenv("DB_NAME"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        port = os.getenv("DB_PORT")
    )


    #conecta no banco
    db_init(conn)

    #Checa se Conectou no banco correto (Por Segurança)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT current_database()
        """
    )
    database_name = cur.fetchone()[0]
    assert database_name == "TESTS_DATABASE"

    
    # limpa o banco com truncate (Podem estar sujas com dado de algum teste anterior)
    cur.execute(
        """
        TRUNCATE TABLE knowledge_base_ai.files CASCADE;
        TRUNCATE TABLE knowledge_base_ai.pipeline;
        """
    )
    conn.commit()
    
    yield conn
    conn.close()
  