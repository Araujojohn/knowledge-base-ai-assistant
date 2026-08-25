# Evaluation

Does the agent actually answer correctly?

This harness takes questions you wrote by hand, sends each one through the
**real** agent — real retrieval, real model, real tools, the same settings
production uses — and has a second model grade every answer against the answer
you expected.

## Quick start

**1. Create your question set.**

```bash
cp evals/v1_golden_set.example.json evals/v1_golden_set.json
```

**2. Fill it with your own questions.** It's a plain JSON list. Each entry has
three fields and nothing else:

```json
[
  {
    "id": 1,
    "question": "what account is acct_00099120 in the vault?",
    "expected_answer": "Northwind Motors, a dealership client. Google Ads customer 555-000-1234. Models: Falcon, Harrier, Kestrel."
  }
]
```

- `id` — any number. It's how you point at the question in the report.
- `question` — exactly what you would type to the agent.
- `expected_answer` — the facts a correct answer must contain. Write the facts,
  not a polished paragraph: the judge compares meaning, not wording.

Twenty questions is a good size to aim for. Ten is already useful.

**3. Run it.**

```bash
python -m evals.run_evals
```

Run it from the repo root — the harness imports `graph`, so the root has to be
on `sys.path`. It needs the same environment variables the app needs (Postgres,
OpenAI, Cohere, GitHub), plus `OPENAI_API_TOKEN` for the judge.

A report lands in `evals/runs/`, named with the date and time.

## Writing questions that are worth asking

Two rules decide whether a question earns its place.

**A generic model must not be able to answer it without your data.** "What does
`runOnceForAllItems` do in n8n?" measures the model, not your system — any
assistant answers it. "Which client uses account `acct_00099120`?" can only be
answered from your knowledge base.

**The answer must not rot.** If a fact changes over time, put the time inside
the question: *"in March 2026, which model had the worst cost per lead?"*
Without that anchor your expected answer goes stale the moment new data lands,
and the eval starts failing answers that are actually right.

The most valuable questions are the ones whose correct answer is **"I don't have
that."** Ask for a secret your notes deliberately never store, or for a client
that has no file. An agent that invents a plausible-looking ID is far more
dangerous than one that admits it doesn't know, and nothing else in your test
suite catches it.

## Reading the report

Top level:

| Field | Meaning |
|---|---|
| `score` | percentage of questions judged correct |
| `total_questions` / `correct_aswers` | the raw counts behind the score |
| `model` | the agent model versions that actually answered |
| `total_latency` / `avg_latency_per_question` | how long it took |
| `total_input_tokens` / `total_output_tokens` | what it cost |
| `breakdown_per_question` | one entry per question |

Each entry in the breakdown carries the question and your expected answer, the
answer the agent produced, `correct` (the verdict), `eval` (why the judge
decided that), plus the model, tokens and latency for that question.

Start from the failures and read `eval` first. It tells you whether the agent
missed a fact, contradicted one, or answered a different question — three
problems with three different fixes.

## How it works

For each question in the set:

1. `run_llm` sends the question through `send_message_to_ai` with a random
   thread id, so questions don't leak into each other's memory.
2. It reads the final answer off the stream, along with the tokens spent and
   the model version that produced it.
3. `run_judge` sends the question, your expected answer and the agent's answer
   to the judge, which returns `{correct, reason}`.

The results are aggregated and written to `evals/runs/`.

## The judge

The judge reads the question, your expected answer and the agent's answer, then
returns a verdict plus its reasoning. Its rubric is `judger_prompt` in
`run_evals.py` — edit it there if your definition of "correct" differs.

The rule that matters most is already in it: **extra detail is not an error**
unless it contradicts the expected answer. Without that rule the judge invents
its own standard. An early run failed three answers that were substantially
right, purely for saying more than the reference said.

The judge model is `judger_model`, at the top of the same file, and it is
recorded in the report — a score depends on who graded it as much as on who
answered.

One thing to keep in mind while reading a verdict: the judge only ever sees your
expected answer, so it cannot tell "extra and correct" from "extra and
invented". If that distinction matters for your set, list the required facts per
question instead of writing a prose reference.

## Your data stays yours

`evals/v1_golden_set.json` and `evals/runs/` are both in `.gitignore`.

A question set describes the contents of a private knowledge base, and a report
embeds every answer the agent produced — which is that knowledge base, quoted
back. Only the harness and the fictional example live in this repository.
