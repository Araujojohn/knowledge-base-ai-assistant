"""Ponto único por onde passa toda chamada paga: modelo do agente, embedding, rerank e juiz.

Fora do scripts/evals.py (EVALS_PELO_SCRIPT ausente) a chamada paga estoura: o CI e o pytest do dia a dia nunca
pagam (28/10: o test_rag chamava OpenAI e Cohere de verdade em todo push).

Pelo script, cada resposta é guardada em tests/evals/gravacoes/ (fora do git: as respostas citam o vault) pela chave
teste + pedido exato + quantas vezes o mesmo pedido já saiu naquele teste. Pedido igual devolve a resposta real que o
modelo já deu, de graça; pedido que mudou (prompt, ferramenta, modelo, conteúdo do vault) paga e grava.
  EVALS_GRAVACAO=gratis  pedido sem gravação estoura em vez de pagar (conferir conserto de código)
  EVALS_GRAVACAO=renova  paga tudo de novo (só desempenho: medir o acaso ou comparar modelos)
Não há relógio a fixar: nenhum prompt leva hora, data ou sorteio (prompts.py) e o thread_id não vai no pedido.

Fica em volta do transporte do httpx porque os 4 SDKs (anthropic, openai, google-genai, cohere) passam por ele.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import httpx

HOSTS_PAGOS = ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
               "api.cohere.com", "api.cohere.ai")
GRAVACOES = Path(__file__).parent / "evals" / "gravacoes"

# US$ por 1 milhão de tokens (entrada, saída). Estimativa por cima, conferir com a fatura; modelo fora da tabela
# conta pelo mais caro, pra verba nunca sair por baixo.
PRECOS = {
    "claude-haiku": (1.00, 5.00), "claude-sonnet": (3.00, 15.00), "claude-opus": (15.00, 75.00),
    "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50), "gemini": (1.25, 10.00),
    "gpt-5.4-mini": (0.75, 4.50), "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.0),
}
PRECO_DESCONHECIDO = (15.00, 75.00)
RERANK_USD_POR_BUSCA = 0.002  # Cohere rerank-v3.5: US$ 2 por 1.000 buscas

teste_atual = ""
conta: dict[str, dict] = defaultdict(
    lambda: {"cheio": 0.0, "gasto": 0.0, "chamadas": 0, "gravadas": 0, "segundos": 0.0, "modelos": []})
_vezes: dict[tuple[str, str], int] = defaultdict(int)


def _pelo_script() -> bool:
    return os.environ.get("EVALS_PELO_SCRIPT") == "1"


def _modo() -> str:
    return os.environ.get("EVALS_GRAVACAO", "")


def custo(corpo: bytes) -> tuple[float, str]:
    """(US$, modelo que respondeu) pelo uso que a própria resposta informa; resposta sem uso conta 0."""
    try:
        dados = json.loads(corpo)
    except ValueError:
        return 0.0, ""
    if not isinstance(dados, dict):
        return 0.0, ""
    buscas = ((dados.get("meta") or {}).get("billed_units") or {}).get("search_units")
    if buscas:
        return buscas * RERANK_USD_POR_BUSCA, "cohere-rerank"
    modelo = str(dados.get("model") or dados.get("modelVersion") or "")
    uso = dados.get("usage") or {}
    gemini = dados.get("usageMetadata") or {}
    entrada = uso.get("input_tokens", uso.get("prompt_tokens", 0)) + gemini.get("promptTokenCount", 0)
    saida = (uso.get("output_tokens", uso.get("completion_tokens", 0))
             + gemini.get("candidatesTokenCount", 0) + gemini.get("thoughtsTokenCount", 0))
    preco_entrada, preco_saida = next((p for nome, p in sorted(PRECOS.items(), key=lambda x: -len(x[0]))
                                       if modelo.startswith(nome)), PRECO_DESCONHECIDO)
    return (entrada * preco_entrada + saida * preco_saida) / 1_000_000, modelo


def _recusa(request: httpx.Request) -> None:
    raise RuntimeError(f"chamada paga pra {request.url.host} fora do scripts/evals.py: teste grátis não chama "
                       "modelo, embedding nem rerank (eval: python scripts/evals.py afetados --rodar)")


def _chave(request: httpx.Request) -> str:
    pedido = hashlib.sha256(request.method.encode() + str(request.url).encode() + request.content).hexdigest()
    _vezes[(teste_atual, pedido)] += 1
    return hashlib.sha256(f"{teste_atual}|{pedido}|{_vezes[(teste_atual, pedido)]}".encode()).hexdigest()[:40]


def _gravada(request: httpx.Request) -> tuple[Path, dict | None]:
    arquivo = GRAVACOES / f"{_chave(request)}.json"
    if arquivo.exists() and _modo() != "renova":
        return arquivo, json.loads(arquivo.read_text(encoding="utf-8"))
    if _modo() == "gratis":
        raise RuntimeError(f"modo grátis: pedido novo pra {request.url.host} sem resposta gravada ({teste_atual})")
    return arquivo, None


def _guardar(arquivo: Path, request: httpx.Request, resposta: httpx.Response, corpo: bytes, segundos: float) -> dict:
    g = {"status": resposta.status_code, "tipo": resposta.headers.get("content-type", "application/json"),
         "corpo": base64.b64encode(corpo).decode(), "segundos": round(segundos, 2),
         # pra achar por que um pedido não bateu com a gravação: diff do pedido de duas rodadas
         "teste": teste_atual, "pedido": request.content.decode("utf-8", "replace")}
    if resposta.status_code < 400:
        GRAVACOES.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(g), encoding="utf-8")
    return g


def _servir(request: httpx.Request, g: dict, gravada: bool) -> httpx.Response:
    corpo = base64.b64decode(g["corpo"])
    usd, modelo = custo(corpo)
    c = conta[teste_atual]
    c["chamadas"] += 1
    c["cheio"] += usd
    c["segundos"] += g["segundos"]
    if gravada:
        c["gravadas"] += 1
    else:
        c["gasto"] += usd
    if modelo and modelo not in c["modelos"]:
        c["modelos"].append(modelo)
    return httpx.Response(g["status"], headers={"content-type": g["tipo"]}, content=corpo, request=request)


_original = httpx.HTTPTransport.handle_request
_original_async = httpx.AsyncHTTPTransport.handle_async_request


def _gravando(self, request: httpx.Request) -> httpx.Response:
    if request.url.host not in HOSTS_PAGOS:
        return _original(self, request)
    if not _pelo_script():
        _recusa(request)
    request.read()
    arquivo, g = _gravada(request)
    gravada = g is not None
    if g is None:
        inicio = time.perf_counter()
        resposta = _original(self, request)
        g = _guardar(arquivo, request, resposta, resposta.read(), time.perf_counter() - inicio)
    return _servir(request, g, gravada)


async def _gravando_async(self, request: httpx.Request) -> httpx.Response:
    if request.url.host not in HOSTS_PAGOS:
        return await _original_async(self, request)
    if not _pelo_script():
        _recusa(request)
    await request.aread()
    arquivo, g = _gravada(request)
    gravada = g is not None
    if g is None:
        inicio = time.perf_counter()
        resposta = await _original_async(self, request)
        g = _guardar(arquivo, request, resposta, await resposta.aread(), time.perf_counter() - inicio)
    return _servir(request, g, gravada)


httpx.HTTPTransport.handle_request = _gravando
httpx.AsyncHTTPTransport.handle_async_request = _gravando_async
