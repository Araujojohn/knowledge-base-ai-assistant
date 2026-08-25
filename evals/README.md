# Evaluation

Does the agent actually answer correctly?

Write the questions. Write what a right answer has to say. The harness runs each
one through the **real** agent — real retrieval, real model, real tools, the
same settings production uses — and a second model grades every answer against
what you wrote.

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
| `fact_coverage` | percentage of the facts in your references that the answers actually carried |
| `total_facts_extracted` / `total_facts_covered` | the raw counts behind that |
| `model` | the agent model versions that actually answered |
| `total_latency` / `avg_latency_per_question` | how long it took |
| `total_input_tokens` / `total_output_tokens` | what it cost |
| `breakdown_per_question` | one entry per question |

Each entry in the breakdown carries the question and your expected answer, the
answer the agent produced, `correct` (the verdict), `facts_extracted` and
`facts_covered` for that question, `eval` (why the judge decided what it did),
plus the model, tokens and latency.

Start from the failures and read `eval` first. It names the central point the
judge identified, so you can see whether it read the question the way you meant
it before you go blaming the agent.

**Two numbers, two jobs.** `score` answers "did the agent answer correctly" and
is the one to quote. `fact_coverage` answers "how much of what I wrote down did
it actually carry", and it moves in smaller steps because it counts facts rather
than questions — twenty questions holding eighty facts give it four times the
resolution. Use it to notice changes the verdict is too coarse to show. A
question can be correct at 1 of 5 facts: the answer reached the point and left
most of the detail behind.

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

The judge grades one thing: **did the answer reach the central point of your
reference.** Not whether it matched it line by line.

That distinction is the whole game. Give a judge a paragraph and ask "is this
right", and it quietly turns your paragraph into a checklist — then fails
answers that were correct but shorter than what you wrote. So the rubric says it
outright: missing a supporting detail never fails an answer, and neither does
saying more than the reference says. Contradicting the reference does.

It also has to name the central point it identified before it gives a verdict.
When a verdict looks wrong, you can see whether the judge misread the question
before you go blaming the agent.

**Check the judge before you trust it.** Label a run yourself — twenty answers,
twenty minutes — and compare. If it disagrees with you often, the score is
measuring the judge, not the agent, and no amount of tuning the agent will move
it. The rubric lives in `judger_prompt` and the model in `judger_model`, both at
the top of `run_evals.py`, and the model goes into every report: a score depends
on who graded it as much as on who answered.

In the same pass the judge counts how many facts your reference states and how
many the answer carried. Those counters are deliberately walled off from the
verdict, and the prompt says so in as many words. Let them start driving it and
you are back to failing right answers for being brief.

One limit worth knowing: the judge only ever sees your reference, so it cannot
tell "extra and true" from "extra and invented". If that distinction matters for
your set, list the required facts per question instead of writing prose.

## Your data stays yours

`evals/v1_golden_set.json` and `evals/runs/` are both in `.gitignore`.

A question set describes the contents of a private knowledge base, and a report
embeds every answer the agent produced — which is that knowledge base, quoted
back. Only the harness and the fictional example live in this repository.
