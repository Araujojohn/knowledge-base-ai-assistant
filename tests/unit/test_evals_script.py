"""scripts/evals.py sem rodar eval nenhum: o que cada caso usa, o que está provado, a verba."""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("evals_script", Path(__file__).parents[2] / "scripts" / "evals.py")
evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evals)

NAO_TEM = "tests/evals/comportamento/test_nao_tem.py"
BUSCA = "tests/evals/comportamento/test_busca.py"
CASO = f"{NAO_TEM}::test_pergunta_sobre_conta_que_nao_existe_nao_devolve_id"
HOJE = datetime.now().date().isoformat()


def linha(passaram=(), falharam=(), modelo="anthropic:claude-sonnet-5", hashes=None, gasto=0.0, quando=None,
          custo=None):
    return {"quando": quando or f"{HOJE}T10:00", "commit": "abc12345", "tipo": "afetados", "modelo": modelo,
            "passaram": list(passaram), "falharam": list(falharam), "gasto_usd": gasto, "custo": custo or {},
            "hashes": evals_hashes(NAO_TEM) if hashes is None else hashes}


def evals_hashes(arquivo):
    return {a: evals.hash_de(a) for a in evals.usa(arquivo)}


def test_caso_do_agente_usa_o_grafo_o_prompt_e_o_golden_set():
    usados = evals.usa(NAO_TEM)

    assert {"graph.py", "nodes.py", "prompts.py", "tools.py", "state.py", NAO_TEM, "conftest.py",
            "requirements.txt", evals.GOLDEN_SET} <= usados
    assert "api.py" not in usados


def test_caso_da_busca_nao_depende_do_prompt():
    usados = evals.usa(BUSCA)

    assert {"rag.py", "tools.py", BUSCA} <= usados
    assert not {"prompts.py", "nodes.py", evals.GOLDEN_SET} & usados


def test_passou_e_nada_mudou_esta_provado():
    sit = evals.situacao([CASO], [linha(passaram=[CASO])], "anthropic:claude-sonnet-5")

    assert sit[CASO][0] == "provado"


def test_arquivo_usado_mudou_tira_a_prova():
    hashes = {**evals_hashes(NAO_TEM), "prompts.py": "outro"}

    status, _, mudados = evals.situacao([CASO], [linha(passaram=[CASO], hashes=hashes)], None)[CASO]

    assert (status, mudados) == ("mudou", ["prompts.py"])


def test_import_novo_sem_hash_na_rodada_tira_a_prova():
    hashes = evals_hashes(NAO_TEM)
    del hashes["state.py"]

    assert evals.situacao([CASO], [linha(passaram=[CASO], hashes=hashes)], None)[CASO][0] == "mudou"


def test_golden_set_ausente_no_ci_vale_o_registro(monkeypatch):
    hashes = evals_hashes(NAO_TEM)
    original = evals.hash_de
    monkeypatch.setattr(evals, "hash_de", lambda a: None if a == evals.GOLDEN_SET else original(a))

    assert evals.situacao([CASO], [linha(passaram=[CASO], hashes=hashes)], None)[CASO][0] == "provado"


def test_falhou_por_ultimo_nao_esta_provado_mesmo_tendo_passado_antes():
    linhas = [linha(passaram=[CASO]), linha(falharam=[CASO])]

    assert evals.situacao([CASO], linhas, None)[CASO][0] == "falhou"


def test_prova_em_outro_modelo_nao_vale_pro_modelo_de_agora():
    linhas = [linha(passaram=[CASO], modelo="google_genai:gemini-2.5-flash-lite")]

    assert evals.situacao([CASO], linhas, "anthropic:claude-sonnet-5")[CASO][0] == "nunca"
    assert evals.situacao([CASO], linhas, None)[CASO][0] == "provado"  # o portão aceita qualquer modelo


def test_custo_previsto_usa_o_medido_e_cobre_o_que_nunca_mediu():
    linhas = [linha(custo={CASO: 0.04})]

    assert evals.custo_previsto([CASO, f"{BUSCA}::test_x"], linhas) == pytest.approx(0.04 + evals.CUSTO_SEM_MEDIDA_USD)


def test_gasto_de_hoje_ignora_outros_dias():
    linhas = [linha(gasto=0.30), linha(gasto=5.0, quando="2026-01-01T10:00")]

    assert evals.gasto_de_hoje(linhas) == pytest.approx(0.30)


def test_verba_estourada_para_sem_rodar():
    with pytest.raises(SystemExit, match="libera-verba"):
        evals.conferir_verba([linha(gasto=0.80)], previsto=0.20, liberada=False)


def test_verba_liberada_pelo_john_roda():
    evals.conferir_verba([linha(gasto=0.80)], previsto=0.20, liberada=True)


def test_dentro_da_verba_roda():
    evals.conferir_verba([linha(gasto=0.10)], previsto=0.20, liberada=False)


def test_crlf_e_lf_dao_o_mesmo_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "RAIZ", tmp_path)
    (tmp_path / "lf.py").write_bytes(b"a\nb\n")
    (tmp_path / "crlf.py").write_bytes(b"a\r\nb\r\n")

    assert evals.hash_de("lf.py") == evals.hash_de("crlf.py")
