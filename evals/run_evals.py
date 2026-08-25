import os
from dotenv import load_dotenv
import json
from graph import send_message_to_ai
import random
from openai import OpenAI
from pydantic import BaseModel
import asyncio
from pathlib import Path    
from datetime import datetime 
import time

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_TOKEN")
openai = OpenAI(api_key=openai_api_key)

GOLDEN_SET_PATH = Path(__file__).parent / "v1_golden_set.json"
golden_set = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))

output_path = (
    Path(__file__).parent / "runs" / f"{GOLDEN_SET_PATH.stem}_{datetime.now():%Y-%m-%d_%H%M}.json"
)

judger_model = "gpt-5.4-mini-2026-03-17"
judger_prompt = """
You are grading an AI agent's answer against a reference answer taken from a
curated golden set. The reference is the ground truth.

You are not checking whether the two texts look alike. You are checking whether
the agent's answer leaves the reader correctly informed.

Mark correct = true when:
- The agent states every key fact of the reference: names, numbers, dates,
  identifiers, and the core reason all match.
- Wording, structure, ordering and language differ from the reference. That is
  expected and never counts against the answer.
- The agent adds detail the reference does not mention, as long as nothing it
  adds contradicts the reference. A longer, richer answer is not a worse answer.
- The reference says the information is unavailable, and the agent says it does
  not have it instead of producing a value.

Mark correct = false when:
- A key fact of the reference is missing, wrong, or replaced by a vague
  generality (for example, the reference names a specific function or account
  and the agent only describes the idea of one).
- The agent contradicts the reference on any point.
- The agent answers a different question than the one asked.
- The reference says the information is unavailable and the agent invents a
  value anyway.

In `reason`, name the specific key facts the agent hit or missed. Do not comment
on style, length, or on extra information that is consistent with the reference.
"""

class Judge_Response_Schema(BaseModel):
    correct: bool
    reason: str


async def run_llm(prompt, thread_id):
    input_tokens = 0
    output_tokens = 0
    llm_model = None
    answer = None
    try:
        async for airesponse in send_message_to_ai(prompt, thread_id):
            if airesponse["type"] == "metadata":
                input_tokens += airesponse["content"]["input_tokens"]
                output_tokens += airesponse["content"]["output_tokens"]
                llm_model = airesponse["model"]
            if airesponse["type"] == "final_answer":
                answer = airesponse["content"]
            if airesponse["type"] == "error":
                answer = airesponse["content"]
        return answer, llm_model, input_tokens, output_tokens
    except Exception as error:
        return f"llm_call_error: {error}", llm_model, 0, 0



def run_judge(eval_question, llm_aswer, expected_aswer):
    judge = openai.responses.parse(
        model=judger_model,
        input=f"""{judger_prompt}\n
            question: {eval_question}\n
            reference answer: {expected_aswer}\n
            agent answer: {llm_aswer}
            """,
            text_format=Judge_Response_Schema
    )
    judge_eval = judge.output_parsed
    return judge_eval

def random_id():
    thread_id = f"{random.randint(0, 99999)}"
    return thread_id


async def run_golden_set(golden_set, output_path):
    questions_list = golden_set
    questions = 0
    correct_answers = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency = 0
    for index, question in enumerate(questions_list):
        questions += 1
        cronometer_start = time.perf_counter()
        answer, model, input_tokens, output_tokens = await run_llm(question["question"], random_id())
        cronometer_end = time.perf_counter()
        latency = cronometer_end - cronometer_start
        total_latency += latency
        questions_list[index]["answer"] = answer
        questions_list[index]["input_token"] = input_tokens
        questions_list[index]["output_tokens"] = output_tokens
        questions_list[index]["latency"] = latency
        questions_list[index]["model"] = model
        questions_list[index]["judger_model"] = judger_model
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        await asyncio.sleep(0.2)
        try:
            eval = run_judge(question["question"], answer, question["expected_answer"])
            questions_list[index]["correct"] = eval.correct
            questions_list[index]["eval"] = eval.reason
            if eval.correct == True:
                correct_answers += 1
        except Exception as error:
            questions_list[index]["correct"] = False
            questions_list[index]["eval"] = f"llm judge error {error}" 

    models = sorted({q["model"] for q in questions_list})
    average_latency_per_question = round(total_latency / questions, 2)
    score = (correct_answers / questions) * 100
    result = {
        "model": models,
        "score": score,
        "total_questions": questions,
        "correct_aswers": correct_answers,
        "total_latency": total_latency,
        "avg_latency_per_question": average_latency_per_question,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "breakdown_per_question": questions_list
    }   

    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
     
    print(result)
    return result      
        
            
asyncio.run(run_golden_set(golden_set, output_path))
