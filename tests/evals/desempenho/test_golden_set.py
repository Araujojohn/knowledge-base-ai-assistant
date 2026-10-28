"""Desempenho: as perguntas do golden set pelo agente de verdade, cada resposta julgada por um juiz.

`python scripts/evals.py desempenho` mede taxa de acerto, custo e segundos de IA por pergunta. Nunca segura deploy
e nunca confere conserto (isso é tests/evals/comportamento/). Juiz e rubrica vieram do evals/run_evals.py; como
escrever as perguntas: evals/README.md. Medido em 25/08 (20 perguntas): US$ 0,055 a run no Gemini Flash Lite,
US$ 0,94 no Sonnet 5, fora o juiz. Com a gravação, pergunta cujo pedido não mudou sai de graça; `--renova` paga tudo.
"""

import json
import os
from pathlib import Path

import pytest
from openai import OpenAI
from pydantic import BaseModel

from graph import send_message_to_ai

GOLDEN_SET = Path(__file__).resolve().parents[3] / "evals" / "v1_golden_set.json"
PERGUNTAS = json.loads(GOLDEN_SET.read_text(encoding="utf-8")) if GOLDEN_SET.exists() else []

JUDGE_MODEL = "gpt-5.4-mini-2026-03-17"
JUDGE_PROMPT = """
You are grading an AI agent's answer against a reference answer.

Judge one thing only: does the answer get the central point of the reference
right? The central point is what the question was actually asking for.
Everything else in the reference is supporting detail.

correct = true when the answer carries that central point — even if it omits
supporting details, words it differently, or adds material the reference does
not mention.

correct = false when the answer misses the central point, replaces it with a
different one, or contradicts it.

Never fail an answer for:
- missing a secondary fact (a date, an extra reason, one item of a list)
- saying more than the reference says
- different wording, structure, ordering or language

One exception that overrides everything above: when the reference says the
information does not exist or is not available, declining IS the central point.
The answer is false if it supplies any value of the kind that was asked for —
including a value belonging to a different entity, or one offered as a near
match or a related record. Listing neighbouring records counts as supplying a
value. Saying "there is no record" and then naming candidates anyway is false.

In `reason`, state what you took the central point to be, then whether the
answer carried it.

Separately from the verdict, count facts. Break the reference into the
individual pieces of information it states — a name, a number, a date, an
identifier, a cause, a decision — and report:

facts_extracted: how many facts the reference states.
facts_covered:   how many of those appear in the agent's answer.

These counters do NOT affect `correct`. An answer that reaches the central point
is correct even when facts_covered is far below facts_extracted. Material the
answer adds beyond the reference is never counted.
"""


class JudgeVerdict(BaseModel):
    correct: bool
    facts_extracted: int
    facts_covered: int
    reason: str


def judge(question: str, answer: str, expected_answer: str) -> JudgeVerdict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_TOKEN"))
    response = client.responses.parse(
        model=JUDGE_MODEL,
        input=f"""{JUDGE_PROMPT}\n
            question: {question}\n
            reference answer: {expected_answer}\n
            agent answer: {answer}
            """,
        text_format=JudgeVerdict,
    )
    return response.output_parsed


@pytest.mark.asyncio
@pytest.mark.parametrize("pergunta", PERGUNTAS, ids=[f"q{p['id']}" for p in PERGUNTAS])
async def test_resposta_julgada_certa(pergunta, record_property):
    answer, tools_called, tokens = "", [], {"input": 0, "output": 0}
    async for part in send_message_to_ai(pergunta["question"], f"eval-desempenho-{pergunta['id']}"):
        if part["type"] in ("final_answer", "error"):
            answer += part["content"]
        elif part["type"] == "tool_use":
            tools_called.append(part["content"])
        elif part["type"] == "metadata":
            tokens["input"] += part["content"]["input_tokens"]
            tokens["output"] += part["content"]["output_tokens"]
    verdict = judge(pergunta["question"], answer, pergunta["expected_answer"])
    for key, value in {"id": pergunta["id"], "answer": answer, "tools_called": tools_called, "tokens": tokens,
                       "judge_model": JUDGE_MODEL, **verdict.model_dump()}.items():
        record_property(key, value)
    assert verdict.correct, verdict.reason
