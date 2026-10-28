"""Comportamento: pergunta sobre algo que não existe no vault → diz que não tem, sem dar um ID.

Q20 do golden set: em 25/08 falhou no Gemini e no Sonnet (oferecia o registro vizinho em vez de dizer "não tenho").
A pergunta mora em evals/v1_golden_set.json, fora do git (cita cliente real); sem o arquivo o caso falha, não pula.
Conferido por código, sem juiz:
  - nenhum número com 9+ dígitos na resposta (ID de conta Meta ou Google é assim): o valor do tipo pedido;
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


def tem_id(texto: str) -> bool:
    return any(len(re.sub(r"\D", "", m)) >= 9 for m in re.findall(r"\d[\d.\-]*\d", texto))


@pytest.mark.asyncio
async def test_pergunta_sobre_conta_que_nao_existe_nao_devolve_id(record_property):
    pergunta = next(q["question"] for q in json.loads(GOLDEN_SET.read_text(encoding="utf-8")) if q["id"] == 20)
    resposta, ferramentas = "", []
    async for parte in send_message_to_ai(pergunta, "eval-nao-tem"):
        if parte["type"] in ("final_answer", "error"):
            resposta += parte["content"]
        elif parte["type"] == "tool_use":
            ferramentas.append(parte["content"])
    record_property("resposta", resposta)
    record_property("ferramentas", ferramentas)
    assert resposta, "o agente não respondeu"
    assert not tem_id(resposta), f"deu um ID pra algo que não existe: {resposta}"
    assert len(ferramentas) <= TETO_DE_FERRAMENTAS, f"{len(ferramentas)} chamadas de ferramenta: {ferramentas}"
