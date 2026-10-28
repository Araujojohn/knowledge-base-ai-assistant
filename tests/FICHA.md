# Ficha de eval — LangGraph Personal AI Agent

O que a IA faz: responde perguntas do John no WhatsApp e no widget de voz buscando no repo (busca + leitura + escrita de arquivo via commit). Em produção, mas **parada desde 22/10** (conta Anthropic sem crédito, ESTADO_ATUAL → Saúde). As rotinas n8n (manhã, captura com gpt-4o-mini) também usam IA, mas moram no n8n, fora deste repo e desta ficha.

Padrão: [metodologia-de-evals.md](../../../TrustWise/Administração/docs/metodologia-de-evals.md) → "A ficha". Conferido em 2026-10-28 lendo código e registros; nada pago rodou. Linha sem prova = "não conferido", nunca "sim".

| # | Garantia | Status | Prova ou o que falta |
|---|---|---|---|
| | **Não estou testando à toa** | | |
| 1 | Toda chamada paga tem motivo registrado (falhou · mudou o que ele usa · nunca rodou neste modelo); sem motivo, não roda | não | `evals/run_evals.py:122` roda as 20 perguntas toda vez, sem seleção nem registro de prova por caso. |
| 2 | A gravação reaproveita: sem hora, data, sorteio ou ID mudando o pedido | não | Não existe gravação: toda rodada paga agente + juiz de novo (`evals/run_evals.py:80`, `:96`); o prompt é fixo (`prompts.py`), então gravar resolveria. |
| 3 | Nenhum erro conferido por 2 testes pelo mesmo caminho | não conferido | As 20 perguntas de `evals/v1_golden_set.json` nunca foram mapeadas por caminho (rota/ferramenta) pra achar duplicata. |
| 4 | Verba de R$ 5 por dia travada no script; bateu, pergunta ao John | não | Nenhum teto em `evals/run_evals.py`; nada impede rodar o script várias vezes (7 rodadas só em 25/08, `evals/runs/`). |
| | **O que está em produção funciona** | | |
| 5 | Lista dos erros que importam, cada um com teste (tabela abaixo) | não | Lista montada nesta ficha; 5 de 8 erros sem teste. |
| 6 | Cada teste fica vermelho quando o erro é provocado de propósito | não | Nunca foi feito; os testes de `tests/` mockam o modelo e o GitHub, e o eval só tem juiz. |
| 7 | Deploy só sobe com os casos de 1 turno provados na versão (o deploy confere a prova) | não | `.github/workflows/deploy.yml` roda só `pytest tests/` (sem eval nem prova por caso); `tests/test_rag.py` chama embedding OpenAI + rerank Cohere de verdade em todo push (centavos). |
| 8 | As regras dos testes rodam em toda resposta real; o que quebra vira caso | não | Não há conferência de resposta real; o Sentinel (`sentinel_erros.py`) só pega exceção. O modelo vem do banco (`nodes.py:28-38`, `knowledge_base_ai.agent_config`) e nenhum teste confere essa configuração. |

## Erros que importam

| Erro | De onde veio (bug com data, reclamação, risco) | Teste que pega (`arquivo::teste`) | Camada (unit · integration · eval de caso · conversa) |
|---|---|---|---|
| Crédito/chave do modelo zerado: responde "erro interno" por dias sem ninguém saber | LEARNINGS (fallback esconde falha); prod fora desde 22/10 | `tests/test_nodes.py::test_agent_node_returns_the_fallback_response_on_error` confere a frase, **falta** conferir que o alerta chega no Sentinel | unit |
| `search` falha (chave OpenAI sem saldo) e o agente segue navegando arquivo por arquivo | JOURNAL (chave de terceiro, ago/26) | **falta** | unit |
| Pergunta sobre algo que não existe: oferece registro vizinho em vez de dizer "não tenho" | Q20 do eval, falhou no Gemini e no Sonnet (ESTADO_ATUAL, LEARNINGS) | `evals/v1_golden_set.json` id 20, só via juiz; **falta** caso de 1 pergunta conferido por código | conversa (juiz) → devia ser eval de caso |
| Excesso de tool calls (10 rodadas numa pergunta simples) | LEARNINGS (caiu pra 4 com hierarquia de ferramentas) | **falta** (o relatório do eval nem guarda as tool calls) | eval de caso |
| Janela de mensagens corta no meio de tool call e o Gemini recusa | `nodes.py:65` (`safe_message_window`) | **falta** | unit |
| `chunk()` perde trechos sem erro (14 de 22) | JOURNAL | `tests/test_rag.py::test_rag_pipeline_and_search_tool_chunk_retrieval`, só 1 arquivo pequeno; **falta** caso com só-header e header+corpo | integration |
| `write` sobrescreve ou cria arquivo errado no repo do John | risco: ação que vira commit | `tests/test_tools.py::test_write_tool_updates_file_correctly_when_sha_is_provided` · `::test_write_tool_creates_new_file_correctly_when_no_sha_is_provided` | unit |
| Limite de recursão: usuário fica sem resposta | `graph.py:159` | **falta** | unit |

Erro sem teste: coluna "Teste" = **falta**.

## Falta, em ordem

1. Gravação + modo grátis + prova por caso no `run_evals.py` (resposta do agente e do juiz guardadas pelo pedido exato), com verba de R$ 5/dia e rodando só o caso que mudou.
2. Testes grátis do que já quebrou: alerta no Sentinel quando o modelo ou a `search` falham, `safe_message_window`, limite de recursão.
3. Q20 vira eval de caso de 1 pergunta conferido por código (resposta sem valor do tipo pedido) e o eval passa a guardar as tool calls, com teto de rodadas conferido.
4. Quebrar de propósito (prompt e código) e ver se algum teste fica vermelho.
5. CI confere a prova por caso antes de subir e testa a configuração do modelo que vem do banco.
6. Regras dos testes rodando sobre as respostas reais (log do `/chat`), o que quebrar vira caso.
