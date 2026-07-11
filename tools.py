import httpx
from dotenv import load_dotenv
import os
from langchain_core.tools import tool
import base64

load_dotenv()
client = httpx.AsyncClient()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
owner = os.getenv("GITHUB_OWNER")
repo = os.getenv("GITHUB_REPO")


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

tools = [read, list_files, write]