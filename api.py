# FastAPI: routes, endpoints, contracts
## Entrada e saída da aplicação.
## Recebe requisições e devolve respostas.

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import secrets
import hmac, hashlib
import uvicorn
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from pydantic import BaseModel
import avisa
import asyncio
import os
from dotenv import load_dotenv
from openai_realtime import create_openai_realtime_session
from rag import rag_pipeline
from graph import send_message_to_ai
import json

load_dotenv()

app = FastAPI()
security = HTTPBasic()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="10.0.1.0/24")


class ChatRequest(BaseModel):
    message: str
    reply_to: str


class RealtimeQueryRequest(BaseModel):
    message: str
    session_id: str


# -----Helpers-----
def verify_page_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_password = secrets.compare_digest(
        credentials.password, os.getenv("FRONTEND_PASSWORD")
    )
    if not correct_password:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def verify_whatsapp_chat_token(x_n8n_secret: str = Header()):
    """
    Security | Checks the request in "/chat" for the X-N8N-Secret header
    to match against the backend .env key, so only the n8n workflow can call it.
    """

    if x_n8n_secret != os.getenv("N8N_CHAT_SECRET"):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def stream_realtime_response(message: str, session_id: str):
    async for chunk in send_message_to_ai(message, session_id):
        yield json.dumps(chunk) + "\n"


# -----Endpoints-----


@app.get("/health")
@limiter.limit("10/minute")
async def health(request: Request):
    return {"message": "API Healthy and Working"}


@app.post("/chat", dependencies=[Depends(verify_whatsapp_chat_token)])
@limiter.limit("10/minute")
async def chat(request: Request, message: ChatRequest):
    async for airesponse in send_message_to_ai(message.message, message.reply_to):
        await avisa.send_to_whatsapp(
            message=airesponse["content"], number=message.reply_to
        )
    return {"message": f"AI successfully responded to {message.reply_to}"}


@app.post("/ragsync")
@limiter.limit("30/minute")
async def ragsync(request: Request):

    body = await request.body()
    key = request.headers.get("X-Hub-Signature-256")

    gh_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    expected_hash = (
        "sha256="
        + hmac.new(gh_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    )

    if key is not None and hmac.compare_digest(key, expected_hash):
        response = await asyncio.to_thread(rag_pipeline)
        return {"message": response}
    else:
        raise HTTPException(status_code=401, detail="Invalid signature")
    


@app.post("/realtime/query", dependencies=[Depends(verify_page_auth)])
@limiter.limit("10/minute")
async def realtime_query(request: Request, message: RealtimeQueryRequest):
    return StreamingResponse(
        stream_realtime_response(message.message, message.session_id),
        media_type="application/x-ndjson",
    )


@app.post("/realtime/new_session", dependencies=[Depends(verify_page_auth)])
@limiter.limit("10/minute")
async def realtime_new_session(request: Request) -> str:
    """
    Creates OpenAI realtime api Session
    Returns a 10min session key to be used for browser to open WEBRTC connection
    """

    session = await create_openai_realtime_session()
    return session


@app.get("/mnemosyne/app.js", dependencies=[Depends(verify_page_auth)])
@limiter.limit("10/minute")
async def widget_js(request: Request):
    return FileResponse("mnemosyne/app.js", media_type="application/javascript")


@app.get("/mnemosyne", dependencies=[Depends(verify_page_auth)])
@limiter.limit("10/minute")
async def widget_page(request: Request):
    return FileResponse("mnemosyne/index.html")
