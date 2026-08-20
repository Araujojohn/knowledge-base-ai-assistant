import httpx
from dotenv import load_dotenv
import os
from langchain_core.tools import tool
import base64
from openai import OpenAI
import requests
import psycopg
import json
import cohere

load_dotenv()
client = httpx.AsyncClient()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
owner = os.getenv("GITHUB_OWNER")
repo = os.getenv("GITHUB_REPO")

openai_api_key = os.getenv("OPENAI_API_TOKEN")
reranker_api_key = os.getenv("COHERE_API_KEY")



##---Helpers---
openai_client = None
def get_openai_client():
    """Return the cached OpenAI client, creating it on first call."""
    global openai_client
    if openai_client is None:
        openai_client = OpenAI(api_key=openai_api_key)
    return openai_client

reranker_client = None
def get_reranker_client():
    """Return the cached Cohere client, creating it on first call."""
    global reranker_client
    if reranker_client is None:
        reranker_client = cohere.ClientV2(api_key=reranker_api_key)
    return reranker_client

def get_db_connection():
    return psycopg.connect(
        host = os.getenv("DB_HOST"),
        dbname = os.getenv("DB_NAME"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        port = os.getenv("DB_PORT")
    )




@tool
async def read(path: str) -> str:
    """
    Lê um arquivo do github a partir da URL e retorna o conteúdo em texto.
    Use só quando já souber o caminho exato do arquivo (ex: veio do CLAUDE.md,
    do `search`, ou o usuário citou o nome). Não chute caminho.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.raw"
    }

    response = await client.get(
        url = url,
        headers = headers,
    )

    response.raise_for_status()
    result = response.text

    return result


@tool
async def list_files(
    path: str = ""
    ) -> str:

    """
    Lista os arquivos de uma pasta e retorna uma lista com os caminhos.
    Use só quando já souber a pasta específica que precisa navegar. Não sabe
    o caminho? Leia o CLAUDE.md primeiro — não chute pasta.
    deixar o parametro "path" vazio mostra a raiz do repo
    """

    if path == "":
     url = f"https://api.github.com/repos/{owner}/{repo}/contents"
    else:
     url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"


    headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.json"
    }

    params={"ref": "main"}

    response = await client.get(
        url = url,
        headers = headers,
        params = params
    )

    response.raise_for_status()

    data = response.json()

    result = ""
    for items in data:
     for key, value in items.items():
      if key == "path":
       result = result + f"{value}\n"

    return result


@tool
async def write(
    path: str,
    content: str,
    commit_message: str,
    ) -> str:
    """
    Edita/cria um arquivo do github a partir da URL.
    use quando precisar criar/editar/atualizar uma informação ou arquivo na base de conhecimento
    importante: ao editar endpoint espera receber o campo "content" com o arquivo inteiro, não apenas a parte alterada,
    """
    content_base64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json"
    }


    ##Checks the endpoin for the given /path, ands returns its SHA if the file exists
    try:
     get_sha = await client.get(
        url = url,
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
     )
     get_sha.raise_for_status()
     file_sha = get_sha.json()["sha"]
    except httpx.HTTPStatusError as error:
      if error.response.status_code == 404:
       file_sha = "none"
      else:
        raise


    if file_sha == "none":
     body = {
        "message": f"{commit_message}",
        "content": f"{content_base64}",
     }
    else:
     body = {
        "message": f"{commit_message}",
        "content": f"{content_base64}",
        "sha": f"{file_sha}"
     }


    response = await client.put(
        url = url,
        headers = headers,
        json = body
    )

    response.raise_for_status()

    result = response.json()["content"]["path"]

    return result


@tool
def search(
  query: str,
  ):
  """
  Busca Hibrida — ferramenta PADRÃO pra qualquer necessidade de informação, tenta essa
  primeiro, mesmo pra perguntas amplas (Busca Semantica via embeddings + keywords via fts + reranking)
  DICA: Enriqueça a query, tanto sematicamente como com keywords
  #Embeda pergunta
  #envia query ao postgress pegando top 20 chunks por similaridade a query
  #Converter query em ftsquery e buscar top 20 por FTS rank
  #Une os dois Rankings
  #envia ao cohere rerank api
  """

  conn = get_db_connection()
  cur = conn.cursor()
  try:
   response = get_openai_client().embeddings.create(
      model="text-embedding-3-small",
      input=query
      )
   vectorized_query = response.data[0].embedding


   ##Query Unificada Busca top 20 por similaridade + FTS_score
   cur.execute(
      """
      WITH vector_rank AS (
       SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) AS rank
       FROM knowledge_base_ai.chunks
       ORDER BY embedding <=> %s::vector
       LIMIT 20
      ),
      fts_rank AS(
       SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(content_tsv, plainto_tsquery('simple', %s)) DESC) AS rank
       FROM knowledge_base_ai.chunks
       WHERE content_tsv @@ plainto_tsquery('simple', %s)
       ORDER BY ts_rank(content_tsv, plainto_tsquery('simple', %s)) DESC
       LIMIT 20
      )
      SELECT chunks.id, chunks.header, chunks.content, files.path, SUM(1.0 / (60 + combined.rank)) AS rfs_score
      FROM (
       SELECT id, rank FROM vector_rank
       UNION ALL
       SELECT id, rank FROM fts_rank
       ) AS combined
       JOIN knowledge_base_ai.chunks ON chunks.id = combined.id
       JOIN knowledge_base_ai.files ON chunks.file_id = files.id
       GROUP BY chunks.id, chunks.header, chunks.content, files.path
       ORDER BY rfs_score DESC
       LIMIT 20;
      """,
      (vectorized_query, vectorized_query, query, query, query)
   )

   top_20_chunks_by_rfs = cur.fetchall()
  
   documents = []
   for chunk in top_20_chunks_by_rfs:
    documents.append(chunk[2])


   response = get_reranker_client().rerank(
    model="rerank-v3.5",
    query=query,
    documents=documents,
    top_n=5,
   )

   top_5_documents = [top_20_chunks_by_rfs[result.index] for result in response.results]

   conn.commit()
   return top_5_documents
  finally:
   conn.close()


tools = [read, list_files, write, search]
