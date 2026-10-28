"""Evals só rodam pelo scripts/evals.py; aqui fica o que a rodada devolve pra ele.

`pytest tests/evals` direto pula tudo (EVALS_PELO_SCRIPT, que só o script liga). A gravação e a conta do gasto
moram em tests/gravacao.py; ao fim, tests/evals/runs/ultima_rodada.json traz, por caso, passou ou falhou, o custo
cheio (como se nada estivesse gravado), o gasto de verdade, os segundos de IA e o que o teste guardou
(`record_property`: resposta, veredito do juiz, ferramentas chamadas). runs/ fica fora do git: cita o vault.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests import gravacao

RODADA = Path(__file__).parent / "runs" / "ultima_rodada.json"

_passaram: list[str] = []
_falharam: list[str] = []
_respostas: dict[str, dict] = {}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("EVALS_PELO_SCRIPT") != "1":
        pula = pytest.mark.skip(reason="eval roda pelo scripts/evals.py (afetados --rodar, desempenho), não direto")
        for item in items:
            if item.nodeid.startswith("tests/evals/"):
                item.add_marker(pula)


@pytest.fixture(autouse=True)
def sem_erro_da_ia():
    """O agent_node engole a exceção do modelo e responde a frase de fallback, que passa em todo caso que confere
    "não deu um ID". Erro da IA durante o caso (sem crédito, pedido novo no modo grátis) reprova o caso."""
    yield
    erros = gravacao.conta[gravacao.teste_atual]["erros"]
    assert not erros, f"a IA falhou durante o caso, o resultado não vale: {erros}"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    gravacao.teste_atual = item.nodeid


def pytest_runtest_logreport(report):
    if report.failed and report.nodeid not in _falharam:
        _falharam.append(report.nodeid)
    if report.when == "call":
        if report.passed:
            _passaram.append(report.nodeid)
        if report.user_properties:
            _respostas[report.nodeid] = dict(report.user_properties)


def pytest_sessionfinish(session):
    if os.environ.get("EVALS_PELO_SCRIPT") != "1":
        return
    RODADA.parent.mkdir(exist_ok=True)
    # pulado não é passou; passou na chamada e quebrou no teardown sai pelo `falharam`
    rodada = {"passaram": [n for n in _passaram if n not in _falharam], "falharam": _falharam,
              "conta": gravacao.conta, "respostas": _respostas}
    RODADA.write_text(json.dumps(rodada, ensure_ascii=False, indent=1), encoding="utf-8")
