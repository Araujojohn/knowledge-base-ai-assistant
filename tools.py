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

def get_db_connection():
    return psycopg.connect(
        host = os.getenv("DB_HOST"),
        dbname = os.getenv("DB_NAME"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        port = os.getenv("DB_PORT")
    )

openai_api_key = os.getenv("OPENAI_API_TOKEN")

reranker_api_key = os.getenv("COHERE_API_KEY")


@tool
async def read(path: str) -> str:
    """
    Lê um arquivo do github a partir da URL e retorna o conteúdo em texto.
    use quando precisar ler um arquivo na base de conhecimento
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
    use quando precisar ver ou encontrar os arquivo na base de conhecimento
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
async def search(
  query: str,
  ):
  """
  Busca Hibrida, use quando quiser encontrar alguma informação
  buscando rapidamente em todos os textos e arquivos (Busca Semantica via embeddings + keywords via fts + reranking)
  """
  conn = get_db_connection()
  cur = conn.cursor()
  try:
   client = OpenAI(api_key=openai_api_key)
   response = client.embeddings.create(
      model="text-embedding-3-small",
      input=query
      )
   vectorized_query = response.data[0].embedding

   #Embedar pergunta
   #enviar query ao postgress pegando top 20 chunks por similaridade a query
   cur.execute(
     """
     SELECT id, content
     FROM knowledge_base_ai.chunks
     ORDER BY embedding <=> %s::vector
     LIMIT 20
     """,
     (vectorized_query,)
     )

   top_20_by_vector = cur.fetchall()

   # Converter query em tsquery e buscar top 20 por FTS rank
   cur.execute(
       """
       SELECT id, content
       FROM knowledge_base_ai.chunks
       WHERE content_tsv @@ plainto_tsquery('simple', %s)
       ORDER BY ts_rank(content_tsv, plainto_tsquery('simple', %s)) DESC
       LIMIT 20
       """,
       (query, query)
       )

   top_20_by_keyword = cur.fetchall()

   #unificar em indice unico (RRF)
   id_to_rfs_rank = {}
   id_to_content = {}

   for indice, chunk in enumerate(top_20_by_vector, 1):
     id_to_rfs_rank[chunk[0]] = id_to_rfs_rank.get(chunk[0], 0) + 1/(60 + indice)
     id_to_content[chunk[0]] = chunk[1]

   for indice, chunk in enumerate(top_20_by_keyword, 1):
     id_to_rfs_rank[chunk[0]] = id_to_rfs_rank.get(chunk[0], 0) + 1/(60 + indice)
     id_to_content[chunk[0]] = chunk[1]

   #FUNÇÃO que recebe uma tupla (chunk) e traz o item na segunda posição (score)
   #apenas para ser usada no sorted logo abaixo, senão traria id
   def get_rfs_score(chunk):
    return chunk[1]

   top20_rfs_ids = sorted(id_to_rfs_rank.items(), key=get_rfs_score, reverse=True)[:20]

   top20_id_to_chunks_by_rfs = []
   documents = []
   for id, score in top20_rfs_ids:
     top20_id_to_chunks_by_rfs.append({"id": id, "content": id_to_content.get(id)})
     documents.append(id_to_content.get(id))

   #enviar ao cohere rerank api
   co = cohere.ClientV2(api_key=reranker_api_key)

   response = co.rerank(
     model="rerank-v3.5",
     query=query,
     documents=documents,
     top_n=5,
   )
   top_5_k = []

   for result in response.results:
     top_5_k.append(top20_id_to_chunks_by_rfs[result.index])

   top_5_ids = []
   for chunk in top_5_k:
     top_5_ids.append(chunk["id"])

   cur.execute(
      """
      SELECT chunks.header, chunks.content, files.path
      FROM knowledge_base_ai.chunks
      JOIN knowledge_base_ai.files ON chunks.file_id = files.id
      WHERE chunks.id = ANY(%s)
      """,
      (top_5_ids,)
     )

   result = cur.fetchall()
   conn.commit()
   return result
  finally:
   conn.close()


tools = [read, list_files, write, search]
