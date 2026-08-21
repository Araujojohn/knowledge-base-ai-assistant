import pytest
import os
from dotenv import load_dotenv
from rag import db_init
import psycopg


@pytest.fixture
def test_db(monkeypatch):
    """
    Prepare the database for the rag_pipeline test: point the connection env vars at
    the test database, wipe it clean, hand the open connection to the test, and close
    it afterwards.
    """

    # point the connection env vars at the test database
    monkeypatch.setenv("DB_HOST", os.getenv("DB_HOST"))
    monkeypatch.setenv("DB_PORT", os.getenv("DB_PORT"))
    monkeypatch.setenv("DB_NAME", os.getenv("TESTS_DB_NAME"))
    monkeypatch.setenv("DB_USER", os.getenv("TESTS_DB_USER"))
    monkeypatch.setenv("DB_PASSWORD", os.getenv("TESTS_DB_PASSWORD"))

    conn = psycopg.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT"),
    )

    # create the schema and tables if this database is brand new
    db_init(conn)

    # safety check: refuse to run unless we really are on the test database
    cur = conn.cursor()
    cur.execute(
        """
        SELECT current_database()
        """
    )
    database_name = cur.fetchone()[0]
    assert database_name == "TESTS_DATABASE"

    # wipe the tables - they may still hold rows from a previous run
    cur.execute(
        """
        TRUNCATE TABLE knowledge_base_ai.files CASCADE;
        TRUNCATE TABLE knowledge_base_ai.pipeline;
        """
    )
    conn.commit()

    yield conn
    conn.close()
