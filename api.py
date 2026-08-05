# FastAPI: routes, endpoints, contracts
## Entrada e saída da aplicação.
## Recebe requisições e devolve respostas.

from fastapi import FastAPI, Request, HTTPException
from graph import send_message_to_ai
import uvicorn
from pydantic import BaseModel
import avisa
from rag import rag_pipeline
import asyncio
import os
from dotenv import load_dotenv
import hmac, hashlib

load_dotenv()

class ChatRequest(BaseModel):
    message: str
    reply_to: str


app = FastAPI()

@app.get("/health")
async def health():
 return {"message": "API Healthy and Working"}

@app.post("/chat")
async def chat(message: ChatRequest):
 async for airesponse in send_message_to_ai(message.message, message.reply_to):
  await avisa.send_to_whatsapp(message=airesponse, number=message.reply_to)
 return {"message": f"AI Succefully respondend to {message.reply_to}"}

@app.post("/ragsync")
async def ragsync(request: Request):
 
 body = await request.body()
 key = request.headers.get("X-Hub-Signature-256")

 gh_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
 hash_esperado = "sha256=" + hmac.new(gh_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
 if key is not None and hmac.compare_digest(key, hash_esperado): 
  response = await asyncio.to_thread(rag_pipeline)
  return {"message": response}
 else:
  raise HTTPException(status_code=401, detail="Assinatura inválida")

 