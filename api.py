# FastAPI: routes, endpoints, contracts
## Entrada e saída da aplicação.
## Recebe requisições e devolve respostas.

from fastapi import FastAPI
from graph import send_message_to_ai
import uvicorn
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


app = FastAPI()

@app.get("/health")
async def health():
 return {"message": "API Healthy and Working"}

@app.post("/chat")
async def chat(message: ChatRequest):
 return send_message_to_ai(message.message)