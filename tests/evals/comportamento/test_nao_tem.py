"""Comportamento: pergunta sobre algo que não existe no vault → diz que não tem, sem dar um ID.

Q20 do golden set: em 25/08 falhou no Gemini e no Sonnet (oferecia o registro vizinho em vez de dizer "não tenho").
A pergunta mora em evals/v1_golden_set.json, fora do git (cita cliente real); sem o arquivo o caso falha, não pula.
Conferido por código, sem juiz:
  - a resposta diz que não tem (NAO_TEM);
  - nenhum número com 9+ dígitos (ID de conta Meta ou Google é assim) na linha que cita o nome pedido (campo
    `nome_pedido` da pergunta). Afrouxado em 10/11 (John): citar, com o nome certo, o ID de conta ou da BM que
    existe ("o que tenho é isto") não é erro; erro é dar um ID como se fosse o da conta pedida;
  - no máximo TETO_DE_FERRAMENTAS chamadas de ferramenta (10 rodadas numa pergunta simples caíram pra 4 com a
    hierarquia de ferramentas do prompt, LEARNINGS).
Custo: ~US$ 0,05 no Sonnet (a run de 20 perguntas custou US$ 0,94 em 25/08); depois sai da gravação, de graça.
"""

import json
import re
from pathlib import Path

import pytest

from graph import send_message_to_ai

GOLDEN_SET = Path(__file__).resolve().parents[3] / "evals" / "v1_golden_set.json"
TETO_DE_FERRAMENTAS = 6
NAO_TEM = re.compile(r"não (existe|tenho|tem|há|encontrei|achei|consta|localizei)", re.IGNORECASE)


def tem_id(texto: str) -> bool:
    return any(len(re.sub(r"\D", "", m)) >= 9 for m in re.findall(r"\d[\d.\-]*\d", texto))


@pytest.mark.asyncio
async def test_pergunta_sobre_conta_que_nao_existe_nao_devolve_id(record_property):
    caso = next(q for q in json.loads(GOLDEN_SET.read_text(encoding="utf-8")) if q["id"] == 20)
    pergunta = caso["question"]
    resposta, ferramentas = "", []
    async for parte in send_message_to_ai(pergunta, "eval-nao-tem"):
        if parte["type"] in ("final_answer", "error"):
            resposta += parte["content"]
        elif parte["type"] == "tool_use":
            ferramentas.append(parte["content"])
    record_property("resposta", resposta)
    record_property("ferramentas", ferramentas)
    assert resposta, "o agente não respondeu"
    assert NAO_TEM.search(resposta), f"não disse que não tem: {resposta}"
    linhas_do_pedido = [linha for linha in resposta.splitlines() if caso["nome_pedido"].lower() in linha.lower()]
    assert not any(tem_id(linha) for linha in linhas_do_pedido), f"deu um ID pra algo que não existe: {resposta}"
    assert len(ferramentas) <= TETO_DE_FERRAMENTAS, f"{len(ferramentas)} chamadas de ferramenta: {ferramentas}"
