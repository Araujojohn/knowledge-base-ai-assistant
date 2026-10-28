"""A gravação (tests/gravacao.py) com o transporte de verdade trocado por um falso: nada sai da máquina."""

import json
from collections import defaultdict

import httpx
import pytest

from tests import gravacao

RESPOSTA_ANTHROPIC = {"model": "claude-sonnet-5", "usage": {"input_tokens": 1000, "output_tokens": 100},
                      "content": [{"type": "text", "text": "oi"}]}


@pytest.fixture
def transporte(monkeypatch, tmp_path):
    """Liga o modo script, grava em tmp_path e conta quantos pedidos chegaram ao 'provedor'."""
    chegaram = []

    def falso(self, request):
        chegaram.append(request)
        return httpx.Response(200, json=RESPOSTA_ANTHROPIC)

    async def falso_async(self, request):
        return falso(self, request)

    monkeypatch.setenv("EVALS_PELO_SCRIPT", "1")
    monkeypatch.delenv("EVALS_GRAVACAO", raising=False)
    monkeypatch.setattr(gravacao, "_original", falso)
    monkeypatch.setattr(gravacao, "_original_async", falso_async)
    monkeypatch.setattr(gravacao, "GRAVACOES", tmp_path)
    monkeypatch.setattr(gravacao, "conta", defaultdict(lambda: {"cheio": 0.0, "gasto": 0.0, "chamadas": 0,
                                                                  "gravadas": 0, "segundos": 0.0, "modelos": [],
                                                                  "erros": []}))
    monkeypatch.setattr(gravacao, "_vezes", defaultdict(int))
    monkeypatch.setattr(gravacao, "teste_atual", "tests/evals/comportamento/test_x.py::test_y")
    return chegaram


def pede(corpo):
    return httpx.Client().post("https://api.anthropic.com/v1/messages", json=corpo)


def test_fora_do_script_chamada_paga_estoura(monkeypatch):
    monkeypatch.delenv("EVALS_PELO_SCRIPT", raising=False)
    for host in gravacao.HOSTS_PAGOS:
        with pytest.raises(RuntimeError, match="fora do scripts/evals.py"):
            httpx.Client().post(f"https://{host}/v1/x", json={})


@pytest.mark.asyncio
async def test_fora_do_script_chamada_paga_assincrona_estoura(monkeypatch):
    monkeypatch.delenv("EVALS_PELO_SCRIPT", raising=False)
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="fora do scripts/evals.py"):
            await client.post("https://api.anthropic.com/v1/messages", json={})


def test_host_que_nao_paga_passa_direto(transporte, monkeypatch):
    monkeypatch.delenv("EVALS_PELO_SCRIPT", raising=False)

    pede_github = httpx.Client().get("https://api.github.com/repos/x/y")

    assert pede_github.status_code == 200
    assert len(transporte) == 1
    assert not gravacao.conta


def test_pedido_igual_sai_da_gravacao_de_graca(transporte):
    teste = gravacao.teste_atual
    primeira = pede({"messages": ["oi"]})
    gravacao._vezes.clear()  # rodada nova, mesmo teste

    segunda = pede({"messages": ["oi"]})

    assert len(transporte) == 1
    assert segunda.json() == primeira.json() == RESPOSTA_ANTHROPIC
    c = gravacao.conta[teste]
    assert (c["chamadas"], c["gravadas"]) == (2, 1)
    assert c["gasto"] == pytest.approx((1000 * 3 + 100 * 15) / 1_000_000)
    assert c["cheio"] == pytest.approx(2 * c["gasto"])
    assert c["modelos"] == ["claude-sonnet-5"]


def test_pedido_que_mudou_paga_de_novo(transporte):
    pede({"messages": ["oi"]})
    gravacao._vezes.clear()

    pede({"messages": ["prompt mudou"]})

    assert len(transporte) == 2


def test_o_mesmo_pedido_duas_vezes_no_teste_grava_duas_respostas(transporte):
    pede({"messages": ["oi"]})
    pede({"messages": ["oi"]})

    assert len(transporte) == 2
    assert len(list(gravacao.GRAVACOES.glob("*.json"))) == 2


@pytest.mark.asyncio
async def test_gravacao_assincrona(transporte):
    async with httpx.AsyncClient() as client:
        await client.post("https://api.anthropic.com/v1/messages", json={"messages": ["oi"]})
        gravacao._vezes.clear()
        await client.post("https://api.anthropic.com/v1/messages", json={"messages": ["oi"]})

    assert len(transporte) == 1


def test_modo_gratis_nao_paga_pedido_novo(transporte, monkeypatch):
    pede({"messages": ["oi"]})
    gravacao._vezes.clear()
    monkeypatch.setenv("EVALS_GRAVACAO", "gratis")

    pede({"messages": ["oi"]})
    with pytest.raises(RuntimeError, match="modo grátis"):
        pede({"messages": ["pedido novo"]})

    assert len(transporte) == 1
    assert gravacao.conta[gravacao.teste_atual]["erros"]  # o agente engole a exceção; o eval não pode passar


def test_renova_paga_mesmo_com_gravacao(transporte, monkeypatch):
    pede({"messages": ["oi"]})
    gravacao._vezes.clear()
    monkeypatch.setenv("EVALS_GRAVACAO", "renova")

    pede({"messages": ["oi"]})

    assert len(transporte) == 2


def test_resposta_de_erro_nao_fica_gravada(transporte, monkeypatch):
    monkeypatch.setattr(gravacao, "_original", lambda self, request: httpx.Response(529, json={"error": "overloaded"}))

    pede({"messages": ["oi"]})

    assert not list(gravacao.GRAVACOES.glob("*.json"))
    assert gravacao.conta[gravacao.teste_atual]["erros"] == ["api.anthropic.com respondeu 529"]


def test_erro_de_rede_fica_na_conta_do_caso(transporte, monkeypatch):
    def cai(self, request):
        raise httpx.ConnectError("sem rede", request=request)
    monkeypatch.setattr(gravacao, "_original", cai)

    with pytest.raises(httpx.ConnectError):
        pede({"messages": ["oi"]})

    assert gravacao.conta[gravacao.teste_atual]["erros"]


@pytest.mark.parametrize("resposta, usd, modelo", [
    ({"model": "gpt-4o-mini", "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}, 0.15, "gpt-4o-mini"),
    ({"modelVersion": "gemini-2.5-flash-lite", "usageMetadata": {"promptTokenCount": 1_000_000,
                                                                 "candidatesTokenCount": 1_000_000}},
     0.50, "gemini-2.5-flash-lite"),
    ({"meta": {"billed_units": {"search_units": 1}}}, 0.002, "cohere-rerank"),
    ({"model": "modelo-novo", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}, 15.00, "modelo-novo"),
    ({"model": "text-embedding-3-small", "usage": {"prompt_tokens": 1_000_000}}, 0.02, "text-embedding-3-small"),
])
def test_custo_pelo_uso_que_a_resposta_informa(resposta, usd, modelo):
    assert gravacao.custo(json.dumps(resposta).encode()) == (pytest.approx(usd), modelo)
