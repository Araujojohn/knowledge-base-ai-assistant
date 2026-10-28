"""Evals do Personal Agent gastando só o que a mudança pede (metodologia-de-evals, §4-§6).

    python scripts/evals.py afetados                     ← o que está sem prova, por quê e quanto custa (não roda)
    python scripts/evals.py afetados --rodar             ← roda os casos de comportamento sem prova
    python scripts/evals.py afetados --rodar --gratis    ← só respostas gravadas: pedido novo falha em vez de pagar
    python scripts/evals.py afetados --rodar --so tests/evals/comportamento/test_x.py::test_y   ← depois de um conserto
    python scripts/evals.py desempenho [--rodar --motivo "..."] [--so ...] [--renova]  ← taxa, custo e segundos; nunca segura deploy
    python scripts/evals.py portao                       ← o deploy (CI) chama: suíte grátis + prova do comportamento
    python scripts/evals.py historico                    ← as rodadas registradas, de graça

Provado: o último resultado do caso, no modelo de agora, passou, e nenhum arquivo que ele usa mudou desde então.
  "Usa" = o arquivo do teste, os módulos do agente que ele importa (seguindo os imports), conftest.py,
  requirements.txt e o golden set quando o teste lê. Projeto pequeno e de arquivos planos: a seleção por arquivo
  resolve, sem mapa por cobertura. Cada rodada guarda o hash de cada arquivo que os casos usam (CRLF vira LF: o PC e o
  CI dão o mesmo hash).
Modelo de agora: o que o agente lê do banco (knowledge_base_ai.agent_config, nodes.py). Trocou → nada provado nele.
  O portão (CI) não alcança esse banco: confere a prova em qualquer modelo e mostra em qual foi.
Verba do dia: US$ 0,90 (R$ 5), o gasto real de hoje + o previsto da rodada. Passou → para sem rodar. --libera-verba
  só quando o John diz "libera" na conversa; fica no registro.
Registro: tests/evals/registro.jsonl (no git: é a prova que o portão confere). Respostas e gravações: tests/evals/runs/
  e tests/evals/gravacoes/ (fora do git: citam o vault).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EVALS = RAIZ / "tests" / "evals"
COMPORTAMENTO = "tests/evals/comportamento/"
DESEMPENHO = "tests/evals/desempenho/"
REGISTRO = EVALS / "registro.jsonl"
RODADA = EVALS / "runs" / "ultima_rodada.json"
PORTAO = RAIZ / "tests" / ".portao.json"
GOLDEN_SET = "evals/v1_golden_set.json"
FORA_DO_GIT = {GOLDEN_SET}  # no CI não existe: lá vale o hash do registro
SEMPRE = ("conftest.py", "requirements.txt")
VERBA_DIA_USD = 0.90
CUSTO_SEM_MEDIDA_USD = 0.05  # caso nunca medido: o preço de uma pergunta no Sonnet, por cima


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


# ── o que cada caso usa ───────────────────────────────────────────────────────

def hash_de(caminho: str) -> str | None:
    p = RAIZ / caminho
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16] if p.exists() else None


def modulos_importados(caminho: str) -> set[str]:
    """O arquivo e os .py da raiz do repo que ele importa, seguindo os imports deles."""
    vistos: set[str] = set()
    pendentes = [caminho]
    while pendentes:
        atual = pendentes.pop()
        if atual in vistos:
            continue
        vistos.add(atual)
        for no in ast.walk(ast.parse((RAIZ / atual).read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                nomes = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.module and not no.level:
                nomes = [no.module]
            else:
                continue
            pendentes += [f"{n.split('.')[0]}.py" for n in nomes if (RAIZ / f"{n.split('.')[0]}.py").exists()]
    return vistos


def usa(arquivo_de_eval: str) -> set[str]:
    arquivos = modulos_importados(arquivo_de_eval) | set(SEMPRE)
    if "v1_golden_set" in (RAIZ / arquivo_de_eval).read_text(encoding="utf-8"):
        arquivos.add(GOLDEN_SET)
    return arquivos


def casos(pasta: str = COMPORTAMENTO) -> list[str]:
    """Os evals da pasta, um por caso, como o pytest coleta. Não chama IA."""
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", pasta],
                       cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 5):  # 5 = nenhum teste
        sys.exit("não deu pra listar os evals (pytest --collect-only):\n" + (r.stdout + r.stderr)[-2000:])
    return sorted(linha for linha in r.stdout.splitlines() if linha.startswith(pasta) and "::" in linha)


# ── o que está provado ────────────────────────────────────────────────────────

def registro() -> list[dict]:
    return [json.loads(linha) for linha in REGISTRO.read_text(encoding="utf-8").splitlines()] if REGISTRO.exists() else []


def mudados(arquivo_de_eval: str, hashes: dict) -> list[str]:
    """Os arquivos que o caso usa e que mudaram desde a rodada (arquivo novo no caminho conta como mudado)."""
    saida = []
    for a in sorted(usa(arquivo_de_eval)):
        agora = hash_de(a)
        if agora is None and a in FORA_DO_GIT:
            continue
        if hashes.get(a, "ausente") != agora:
            saida.append(a)
    return saida


def situacao(todos: list[str], linhas: list[dict], modelo: str | None) -> dict[str, tuple[str, dict | None, list]]:
    """Por caso: (provado | mudou | falhou | nunca, a rodada do último resultado, os arquivos que mudaram).
    modelo None = vale a prova em qualquer modelo (o portão, que não lê o banco do agente)."""
    sit = {}
    for caso in todos:
        ultima = next((v for v in reversed(linhas) if (modelo is None or v["modelo"] == modelo)
                       and caso in v["passaram"] + v["falharam"]), None)
        if ultima is None:
            sit[caso] = ("nunca", None, [])
        elif caso in ultima["falharam"]:
            sit[caso] = ("falhou", ultima, [])
        else:
            m = mudados(caso.split("::")[0], ultima["hashes"])
            sit[caso] = ("mudou" if m else "provado", ultima, m)
    return sit


def modelo_do_agente() -> str:
    """O modelo que o agente usa agora: o mesmo que nodes.py lê do banco."""
    sys.path.insert(0, str(RAIZ))
    import nodes
    return str(nodes.fetch_model_config())


# ── custo e verba ─────────────────────────────────────────────────────────────

def custo_previsto(alvos: list[str], linhas: list[dict]) -> float:
    """Custo cheio (sem gravação, então por cima): o último medido de cada alvo, ou CUSTO_SEM_MEDIDA_USD."""
    total = 0.0
    for alvo in alvos:
        def do_alvo(nodeid: str) -> bool:
            return nodeid == alvo or nodeid.startswith(alvo + "::")
        medido = next((sum(c for n, c in v["custo"].items() if do_alvo(n))
                       for v in reversed(linhas) if any(map(do_alvo, v["custo"]))), None)
        total += CUSTO_SEM_MEDIDA_USD if medido is None else medido
    return total


def gasto_de_hoje(linhas: list[dict]) -> float:
    hoje = datetime.now().date().isoformat()
    return sum(v["gasto_usd"] for v in linhas if v["quando"].startswith(hoje))


def conferir_verba(linhas: list[dict], previsto: float, liberada: bool) -> None:
    """Para antes de pagar se o dia já bateu a verba ou se esta rodada passaria dela."""
    gasto = gasto_de_hoje(linhas)
    if gasto + previsto <= VERBA_DIA_USD:
        return
    if liberada:
        print(f"  verba do dia liberada pelo John: já foram US$ {gasto:.2f}, esta rodada até US$ {previsto:.2f}")
        return
    sys.exit(f"verba do dia: já foram US$ {gasto:.2f} de US$ {VERBA_DIA_USD:.2f} (R$ 5) e esta rodada custaria até "
             f"US$ {previsto:.2f}. Não roda. Só com --libera-verba, quando o John disser \"libera\" na conversa.")


# ── rodar e registrar ─────────────────────────────────────────────────────────

def rodar(alvos: list[str], gravacao: str) -> dict:
    RODADA.unlink(missing_ok=True)
    env = {**os.environ, "EVALS_PELO_SCRIPT": "1", "EVALS_GRAVACAO": gravacao}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *alvos], cwd=RAIZ, env=env)
    if r.returncode not in (0, 1) or not RODADA.exists():
        sys.exit(f"a rodada não terminou (pytest saiu com {r.returncode}): nada registrado")
    return json.loads(RODADA.read_text(encoding="utf-8"))


def registrar(tipo: str, modelo: str, alvos: list[str], rodada: dict, **extra) -> dict:
    conta = rodada["conta"]
    usados = sorted(set().union(*(usa(a.split("::")[0]) for a in alvos)))
    linha = {"quando": datetime.now().isoformat(timespec="minutes"), "commit": git("rev-parse", "HEAD").strip(),
             "tipo": tipo, "modelo": modelo,
             "modelos_resposta": sorted({m for c in conta.values() for m in c["modelos"]}),
             "passaram": sorted(rodada["passaram"]), "falharam": sorted(rodada["falharam"]),
             "gasto_usd": round(sum(c["gasto"] for c in conta.values()), 4),
             "custo": {n: round(c["cheio"], 4) for n, c in conta.items() if n},
             "hashes": {a: hash_de(a) for a in usados}, **extra}
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return linha


def resumo(rodada: dict) -> str:
    conta = rodada["conta"].values()
    gasto, cheio = sum(c["gasto"] for c in conta), sum(c["cheio"] for c in conta)
    chamadas, gravadas = sum(c["chamadas"] for c in conta), sum(c["gravadas"] for c in conta)
    return (f"{len(rodada['passaram'])} passaram, {len(rodada['falharam'])} falharam · gasto US$ {gasto:.3f} "
            f"(sem gravação seria US$ {cheio:.3f}; {gravadas} de {chamadas} chamadas da gravação)")


ROTULO = {"falhou": "falhou na última vez", "mudou": "mudou o que ele usa desde que passou",
          "nunca": "nunca rodou neste modelo", "provado": "provado"}


def mostrar_plano(modelo: str, sit: dict, alvos: list[str], linhas: list[dict]) -> None:
    provados = sum(s == "provado" for s, _, _ in sit.values())
    print(f"\n{modelo}: {provados} de {len(sit)} casos de comportamento provados; {len(alvos)} rodam")
    for alvo in alvos:
        status, v, m = sit.get(alvo, ("pedido", None, []))
        quando = f" (última: {v['quando']}, {v['commit'][:8]})" if v else ""
        porque = f": {', '.join(m)}" if m else ""
        print(f"  {alvo}\n    {ROTULO.get(status, '--so')}{porque}{quando}")
    if alvos:
        print(f"  custo: até US$ {custo_previsto(alvos, linhas):.2f} (sem gravação; o pedido que não mudou sai de graça)")


# ── comandos ──────────────────────────────────────────────────────────────────

def cmd_afetados(args) -> int:
    linhas, modelo = registro(), modelo_do_agente()
    if args.so:
        fora = [a for a in args.so if not a.startswith(COMPORTAMENTO)]
        if fora:
            sys.exit(f"--so é pra caso de comportamento ({COMPORTAMENTO}); desempenho: `desempenho --so`. {fora}")
        alvos, sit = list(args.so), {}
    else:
        sit = situacao(casos(), linhas, modelo)
        alvos = [c for c, (s, _, _) in sit.items() if s != "provado"]
    mostrar_plano(modelo, sit, alvos, linhas)
    if not (args.rodar and alvos):
        return 0
    if not args.gratis:
        conferir_verba(linhas, custo_previsto(alvos, linhas), args.libera_verba)
    rodada = rodar(alvos, "gratis" if args.gratis else "")
    motivos = {a: "--so (conserto)" if args.so else ROTULO[sit[a][0]] for a in alvos}
    registrar("so" if args.so else "afetados", modelo, alvos, rodada, gratis=args.gratis, motivos=motivos,
              **({"verba_liberada": True} if args.libera_verba else {}))
    print(resumo(rodada))
    return 1 if rodada["falharam"] else 0


def cmd_desempenho(args) -> int:
    """Taxa de acerto, custo e segundos de IA por pergunta. Nunca segura nada: sai 0 com qualquer taxa."""
    linhas, modelo = registro(), modelo_do_agente()
    alvos = args.so or casos(DESEMPENHO)
    if not alvos:
        sys.exit(f"nenhuma pergunta de desempenho: falta {GOLDEN_SET} (evals/README.md)")
    print(f"\n{modelo}: desempenho, {len(alvos)} casos; custo até US$ {custo_previsto(alvos, linhas):.2f}"
          + (" (--renova: paga tudo de novo)" if args.renova else " (o pedido que não mudou sai da gravação)"))
    if not args.rodar:
        return 0
    if not args.motivo:
        sys.exit("desempenho só com motivo (--motivo): troca de modelo, mudança grande, antes de liberar pra alguém "
                 "ou o John pediu. Conserto se confere em comportamento, não aqui.")
    conferir_verba(linhas, custo_previsto(alvos, linhas), args.libera_verba)
    rodada = rodar(alvos, "renova" if args.renova else "")
    registrar("desempenho", modelo, alvos, rodada, renova=args.renova, motivos={a: args.motivo for a in alvos},
              **({"verba_liberada": True} if args.libera_verba else {}))
    n = len(rodada["passaram"]) + len(rodada["falharam"])
    conta = rodada["conta"].values()
    fatos = [(r.get("facts_covered", 0), r.get("facts_extracted", 0)) for r in rodada["respostas"].values()]
    cobertos, extraidos = sum(f[0] for f in fatos), sum(f[1] for f in fatos)
    if n:
        print(f"taxa de acerto {len(rodada['passaram'])}/{n} · custo US$ {sum(c['cheio'] for c in conta):.3f} a run"
              f" · {sum(c['segundos'] for c in conta) / n:.1f}s de IA por pergunta"
              f" · cobertura de fatos {cobertos}/{extraidos}")
    relatorio = EVALS / "runs" / f"desempenho_{datetime.now():%Y-%m-%d_%H%M}.json"
    relatorio.write_text(json.dumps(rodada, ensure_ascii=False, indent=1), encoding="utf-8")
    print(resumo(rodada), f"\nrespostas e veredito do juiz: {relatorio.relative_to(RAIZ)}")
    return 0


def cmd_portao(args) -> int:
    """O deploy só sobe com a suíte grátis passando e todo caso de comportamento provado. Não paga nada."""
    sujo = [linha for linha in git("status", "--porcelain", "--untracked-files=no").splitlines()]
    if sujo:
        sys.exit("há mudança não commitada: o portão abre pra um commit\n" + "\n".join(sujo[:10]))
    env = {k: v for k, v in os.environ.items() if k not in ("EVALS_PELO_SCRIPT", "EVALS_GRAVACAO")}
    if subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=RAIZ,
                      env=env).returncode != 0:
        sys.exit("suíte grátis falhou: não sobe")
    sit = situacao(casos(), registro(), modelo=None)
    sem_prova = [c for c, (s, _, _) in sit.items() if s != "provado"]
    if sem_prova:
        mostrar_plano("qualquer modelo", sit, sem_prova, registro())
        sys.exit("comportamento sem prova nesta versão: não sobe. `python scripts/evals.py afetados --rodar`, commita "
                 "tests/evals/registro.jsonl e sobe de novo.")
    modelos = sorted({v["modelo"] for _, v, _ in sit.values() if v})
    head = git("rev-parse", "HEAD").strip()
    PORTAO.write_text(json.dumps({"commit": head, "quando": datetime.now().isoformat(timespec="minutes"),
                                  "casos": len(sit), "provado_em": modelos}), encoding="utf-8")
    print(f"portão aberto pra {head[:8]}: suíte grátis passou, {len(sit)} casos de comportamento provados "
          f"(em {', '.join(modelos) or 'nenhum caso'})")
    return 0


def cmd_historico(args) -> int:
    linhas = registro()
    for v in linhas[::-1][:args.ultimas]:
        print(f"{v['quando']} · {v['commit'][:8]} · {v['tipo']:10} · {v['modelo']} · {len(v['passaram'])} passaram, "
              f"{len(v['falharam'])} falharam · US$ {v['gasto_usd']:.3f}")
    print(f"hoje: US$ {gasto_de_hoje(linhas):.3f} de US$ {VERBA_DIA_USD:.2f}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    a = sub.add_parser("afetados")
    a.add_argument("--rodar", action="store_true")
    a.add_argument("--gratis", action="store_true", help="só respostas gravadas; pedido novo falha em vez de pagar")
    a.add_argument("--so", action="append", help="só este caso (arquivo::teste); repete pra mais de um")
    d = sub.add_parser("desempenho")
    d.add_argument("--rodar", action="store_true")
    d.add_argument("--motivo", help="por que medir agora (fica no registro); obrigatório com --rodar")
    d.add_argument("--so", action="append", help="só este caso de desempenho (arquivo::teste)")
    d.add_argument("--renova", action="store_true", help="paga tudo de novo: medir o acaso ou comparar modelos")
    for comando in (a, d):
        comando.add_argument("--libera-verba", action="store_true",
                             help="roda acima da verba do dia (R$ 5): só quando o John disse \"libera\" na conversa")
    sub.add_parser("portao")
    h = sub.add_parser("historico")
    h.add_argument("--ultimas", type=int, default=10)
    args = p.parse_args()
    comandos = {"afetados": cmd_afetados, "desempenho": cmd_desempenho, "portao": cmd_portao,
                "historico": cmd_historico}
    return comandos[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
