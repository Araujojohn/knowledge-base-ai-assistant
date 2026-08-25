# Evaluation

An end-to-end evaluation of the agent: 20 curated questions go through the real
graph — real retrieval, real model, real tools — and an LLM judge grades each
answer against a hand-written reference.

This measures the **whole pipeline**, not retrieval alone. A wrong answer here
can come from a bad chunk, a bad search query, or a bad generation, and this
harness does not yet tell them apart. Isolating retrieval (Precision@K,
Recall@K, MRR) is the next step.

## Running it

```bash
cp evals/v1_golden_set.example.json evals/v1_golden_set.json
python -m evals.run_evals
```

Run it from the repo root — `run_evals.py` imports `graph`, so the root has to
be on `sys.path`. It needs the same environment as the app (Postgres, OpenAI,
Cohere, GitHub) plus `OPENAI_API_TOKEN` for the judge.

Each run writes a timestamped report to `evals/runs/`.

## The golden set

`v1_golden_set.example.json` shows the format. Each entry is
`{id, question, expected_answer}` — nothing else.

**The real set is not in this repo.** It asks about a private vault and the
reference answers contain infrastructure addresses, client account IDs and
personal decisions. `evals/runs/` is ignored for the same reason: a report
embeds every answer the agent produced.

Questions were written by hand, not generated, against two rules:

1. **A generic LLM must not be able to answer it without the vault.** Questions
   about public library behaviour were cut — they measure the model, not the
   system.
2. **The answer must not rot.** Anything time-sensitive carries its own anchor
   in the question ("in March 2026, which model…"), so the reference stays true
   as new data lands in the vault.

The two most valuable questions test the agent *not* inventing: one asks for a
secret the vault deliberately never stores, another for a client that has no
file at all. Both are correct only when the agent says it does not have the
answer.

## The judge

A separate model reads the question, the reference answer and the agent's
answer, and returns `{correct: bool, reason: str}`.

The rubric it works from is in `judger_prompt` (`run_evals.py`). The rule that
matters most: **extra detail is not an error** as long as it doesn't contradict
the reference. Without that rule the judge invented its own standard — an early
run failed three answers that were substantially right, purely for saying more
than the reference said.

## What the report contains

Per run: score, question count, total and per-question latency, input/output
tokens, and the resolved model name. Per question: the agent's answer, its
token cost, its latency, the verdict and the judge's reasoning.

The model is recorded per question and summarised as a list, not stored once at
the top. The config in Postgres holds an alias (`gemini-flash-lite-latest`);
what actually answers is a concrete version (`gemini-3.5-flash-lite`). Recording
the alias would let the underlying model change without the report ever showing
it.

## Known limits

**Two runs are not comparable yet.** The agent samples at `temperature=0.7`, so
the same question produces a different search query, retrieves different chunks
and yields a different answer each time. Two runs 22 minutes apart differed by
30k input tokens — different tool-call paths, not rewording. With one attempt
per question, a score change can be a real regression or just the dice.
Pinning `temperature=0` for eval runs, or averaging several attempts per
question, is what closes that.

**The judge still penalises extra detail sometimes.** It only sees the
reference, so "not in the reference" and "possibly fabricated" look identical
from where it sits. Grading against an explicit list of required facts per
question, instead of a prose reference, would remove the ambiguity.

**Retrieval is not measured on its own.** Every number here is answer-level.
