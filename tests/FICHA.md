# Ficha de eval — LangGraph Personal AI Agent

O que a IA faz: responde perguntas do John no WhatsApp e no widget de voz buscando no repo (busca + leitura + escrita de arquivo via commit). Em produção; o ESTADO_ATUAL diz parada desde 22/10 por crédito Anthropic, mas em 28/10 o `agent_config` do banco aponta pra `google_genai:gemini-flash-lite-latest` (lido pelo `scripts/evals.py afetados`). As rotinas n8n (manhã, captura com gpt-4o-mini) também usam IA, mas moram no n8n, fora deste repo e desta ficha.

Padrão: [metodologia-de-evals.md](../../../TrustWise/Administração/docs/metodologia-de-evals.md) → "A ficha". Conferido em 2026-10-28 rodando a suíte grátis, o script nos modos que não pagam e quebrando código de propósito; nenhum eval pago rodou. Linha sem prova = "não conferido", nunca "sim".

Como rodar: `python scripts/evals.py afetados` (plano e custo) → `--rodar` (paga só o sem prova) → depois de conserto `--rodar --so <arquivo::teste>`; `--gratis` confere conserto de código só com respostas gravadas. Desempenho: `desempenho --rodar --motivo "..."`. Deploy: o CI roda `portao`.

| # | Garantia | Status | Prova ou o que falta |
|---|---|---|---|
| | **Não estou testando à toa** | | |
| 1 | Toda chamada paga tem motivo registrado: o caso falhou, mudou o que ele usa, ou nunca rodou neste modelo. Sem motivo, não roda | sim | Comportamento roda só o que não está provado (`scripts/evals.py:231`), com o motivo de cada caso no registro (`:238`); desempenho não roda sem `--motivo` (`:255`); fora do script toda chamada paga estoura (`tests/gravacao.py:88`, `tests/unit/test_gravacao.py::test_fora_do_script_chamada_paga_estoura`). |
| 2 | A gravação reaproveita: rodada sem mudança de prompt sai quase toda de graça | sim | Chave = teste + pedido exato (`tests/gravacao.py:93`), nos 4 SDKs via httpx (`:180`); modo grátis (`:103`). Nenhum relógio a fixar: nenhum prompt leva hora, data ou sorteio (`prompts.py`) e o thread_id não vai no pedido. Prova com transporte falso: `tests/unit/test_gravacao.py::test_pedido_igual_sai_da_gravacao_de_graca`; ponta a ponta no modo grátis com chave inválida, US$ 0 (28/10). Ainda sem rodada real medida. |
| 3 | Nenhum erro conferido por 2 testes pelo mesmo caminho, e nenhum eval testando o que o código garante | sim | 2 casos de comportamento, caminhos diferentes (busca × resposta do agente). A Q20 também está no golden set, mas lá é medida (desempenho), não conferência. O que só dependia do código virou teste grátis (chunk, janela, recursão, alerta); o `test_rag` pago saiu do CI. |
| 4 | Verba de R$ 5 por dia travada no script; bateu, pergunta ao John | sim | `scripts/evals.py:45` e `:158` (gasto real de hoje + previsto; `--libera-verba` fica no registro); `tests/unit/test_evals_script.py::test_verba_estourada_para_sem_rodar`. |
| | **O que está em produção funciona** | | |
| 5 | Lista dos erros que importam, cada um com teste na camada da diretriz; bug que escapou entra com a data | não | Lista abaixo: 11 erros, todos com teste; 1 é buraco aberto (`search` sem alerta, `xfail` estrito, falta o conserto). Os 2 casos de comportamento nunca rodaram. |
| 6 | Cada teste fica vermelho quando o erro é provocado de propósito | não | 7 mutações no código ficaram vermelhas em 28/10 (alerta do modelo, janela, recursão, frontmatter, header com corpo, trava do CI, reaproveitamento da gravação), e o fallback sem IA passou no caso da Q20 até a trava `tests/evals/conftest.py:35`. Falta: quebrar o prompt e ver os 2 casos de comportamento vermelhos (precisa rodada paga) e os testes antigos do `write`. |
| 7 | Deploy só sobe com os testes grátis passando e o comportamento provado no commit, por qualquer caminho | sim | CI: `.github/workflows/deploy.yml:41` roda `scripts/evals.py portao` antes do build (`:44`): suíte grátis + todo caso provado pelo hash do que ele usa, grava `tests/.portao.json` (`scripts/evals.py:276`, `:293`); sem chave paga no CI. Tarball/CLI: o hook do workspace exige o mesmo arquivo. Rodado em 28/10: fecha (0 de 2 provados). Limite: o modelo mora no banco (`agent_config`), que o CI não lê; a prova vale em qualquer modelo e o portão mostra em qual. |
| 8 | As regras dos testes rodam em toda resposta real; o que quebra passa pela diretriz | não | Não há conferência de resposta real; o Sentinel (`sentinel_erros.py`) só pega exceção. |

## Erros que importam

| Erro | De onde veio (bug com data, reclamação, risco) | Teste que pega (`arquivo::teste`) | Camada |
|---|---|---|---|
| Crédito/chave do modelo zerado: responde "erro interno" por dias sem ninguém saber | LEARNINGS (fallback esconde falha); prod fora desde 22/10 | `tests/unit/test_nodes.py::test_a_model_failure_reaches_the_sentinel` · `::test_agent_node_returns_the_fallback_response_on_error` | unit |
| `search` falha (chave OpenAI sem saldo) e o agente segue navegando arquivo por arquivo, sem alerta | JOURNAL (chave de terceiro, ago/26); conferido 28/10: o `ToolNode(handle_tool_errors=True)` não loga nada | `tests/unit/test_graph.py::test_a_search_failure_reaches_the_sentinel` (`xfail` estrito: **falta o conserto** em `graph.py`/`tools.py`) | unit |
| Pergunta sobre algo que não existe: oferece registro vizinho em vez de dizer "não tenho" | Q20 do eval, falhou no Gemini e no Sonnet (25/08) | `tests/evals/comportamento/test_nao_tem.py::test_pergunta_sobre_conta_que_nao_existe_nao_devolve_id` (nunca rodou) | comportamento |
| Excesso de tool calls (10 rodadas numa pergunta simples) | LEARNINGS (caiu pra 4 com hierarquia de ferramentas) | mesmo caso acima, teto de 6 ferramentas; o desempenho guarda as ferramentas de cada pergunta | comportamento |
| Eval passa com a IA fora: o fallback "erro interno" não tem ID e passava no caso da Q20 | achado 28/10, rodando o caso no modo grátis | `tests/evals/conftest.py::sem_erro_da_ia` · `tests/unit/test_gravacao.py::test_modo_gratis_nao_paga_pedido_novo` | unit |
| Janela de mensagens corta no meio de tool call e o Gemini recusa | `nodes.py` (`safe_message_window`) | `tests/unit/test_nodes.py::test_safe_message_window_never_opens_inside_a_tool_call` | unit |
| `chunk()` perde trechos sem erro (60 de 140 arquivos; 14 de 22 chunks) | JOURNAL | `tests/unit/test_chunk.py` (frontmatter pequeno, header com corpo, header sozinho) | unit |
| A busca não traz o trecho certo | risco: é o caminho de toda resposta | `tests/evals/comportamento/test_busca.py::test_rag_pipeline_and_search_tool_chunk_retrieval` (nunca rodou; guarda a posição) | comportamento |
| `write` sobrescreve ou cria arquivo errado no repo do John | risco: ação que vira commit | `tests/unit/test_tools.py::test_write_tool_updates_file_correctly_when_sha_is_provided` · `::test_write_tool_creates_new_file_correctly_when_no_sha_is_provided` | unit |
| Limite de recursão: usuário fica sem resposta | `graph.py` | `tests/unit/test_graph.py::test_hitting_the_recursion_limit_still_answers_the_user` | unit |
| CI paga IA em todo push | `test_rag.py` chamava OpenAI + Cohere no CI (até 28/10) | `tests/unit/test_gravacao.py::test_fora_do_script_chamada_paga_estoura` | unit |

## Falta, em ordem

1. Consertar a `search` sem alerta (o `xfail` vira teste normal) — código do agente: é do John (postura de professor no CLAUDE.md).
2. Rodar os 2 casos de comportamento uma vez (`afetados --rodar`, ~US$ 0,10 por cima), commitar `tests/evals/registro.jsonl`; até lá o portão segura todo deploy pelo CI.
3. Quebrar o prompt de propósito e ver os 2 casos vermelhos; mutação nos testes do `write`.
4. Portão conferir o modelo do banco (`agent_config`) contra o da prova, ou teste da configuração no banco de teste.
5. Regras dos testes rodando sobre as respostas reais (log do `/chat`), o que quebrar vira caso.
