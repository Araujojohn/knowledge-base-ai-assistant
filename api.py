# FastAPI: routes, endpoints, contracts
## Entrada e saída da aplicação.
## Recebe requisições e devolve respostas.

from fastapi import FastAPI
from graph import send_message_to_ai
import uvicorn
from pydantic import BaseModel
import avisa


class ChatRequest(BaseModel):
    message: str
    reply_to: str


app = FastAPI()

@app.get("/health")
async def health():
 return {"message": "API Healthy and Working"}

@app.post("/chat")
async def chat(message: ChatRequest):
 async for airesponse in send_message_to_ai(message.message):
  await avisa.send_to_whatsapp(message=airesponse, number=message.reply_to)
 return {"message": f"AI Succefully respondend to {message.reply_to}"}