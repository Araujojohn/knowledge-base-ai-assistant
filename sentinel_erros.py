"""Manda todo log de ERROR do serviço pro Sentinel (webhook `[SENTINEL] Service
Errors` no n8n), que vira incidente com o mesmo controle de repetição e escada de
lembretes dos workflows n8n. Antes disso, exceção no chat ou nos jobs internos
só ficava no log do container e ninguém sabia (catálogo do Sentinel, 15/10/2026).

Pega o logger raiz e o `uvicorn.error` (exceção não tratada numa rota: o uvicorn
não propaga pro raiz). Serviço com structlog: `structlog_processor()` na lista de
processors. Não atrasa nem derruba o app: envio numa thread à parte, fila curta,
e a mesma linha de código só manda de novo depois de 10 min (a escada do Sentinel
cuida do resto). Sem `SENTINEL_INGEST_TOKEN` no ambiente, não liga.

Mesmo arquivo nos serviços Python (Ads Analyst, IA SDR Ribeiro, Personal Agent);
mudou aqui, copiar pros outros.
"""
from __future__ import annotations

import contextvars
import logging
import os
import queue
import sys
import threading
import time

import httpx

_URL = "https://n8n.artace.app/webhook/sentinel/service-error"
_THROTTLE_SECONDS = 600
_SERVICE = "personal-agent"
_ACCESS_LOG = "app.access_logs"  # logger do Aegra que escreve a linha de cada request
# Cada request roda na sua task (contexto próprio): guarda quando a exceção dela foi enviada.
# Hora, não sim/não: a task herda o contexto de quem a criou, e uma exceção antiga do
# processo não pode calar a linha 500 de toda request depois dela.
_excecao_na_request: contextvars.ContextVar[float] = contextvars.ContextVar("sentinel_excecao", default=float("-inf"))
_MESMA_REQUEST_SECONDS = 5  # a exceção e a linha 500 da mesma request saem com ms de diferença

logger = logging.getLogger(__name__)


class _Sender:
    """Fila + thread que posta no webhook, com a trava de repetição."""

    def __init__(self, token: str, url: str, service: str) -> None:
        self._token = token
        self._url = url
        self.service = service
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=100)
        self._last_sent: dict[tuple, float] = {}
        threading.Thread(target=self._send_forever, daemon=True, name="sentinel-erros").start()

    def submit(self, key: tuple, where: str, exc: BaseException | None, message: str) -> None:
        now = time.monotonic()
        if now - self._last_sent.get(key, float("-inf")) < _THROTTLE_SECONDS:
            return
        self._last_sent[key] = now
        body = {
            "service": self.service,
            "where": where,
            "error_type": type(exc).__name__ if exc else "LogError",
            "message": (f"{message} | {exc}" if exc else message)[:1500],
        }
        try:
            self._queue.put_nowait(body)
        except queue.Full:
            pass  # rajada de erros: os 100 da fila já avisam

    def _send_forever(self) -> None:
        while True:
            body = self._queue.get()
            try:
                httpx.post(self._url, json=body, headers={"X-Sentinel-Token": self._token}, timeout=10)
            except httpx.HTTPError as e:
                logger.warning("não consegui avisar o Sentinel: %s", e)


class SentinelHandler(logging.Handler):
    def __init__(self, token: str, *, url: str = _URL, service: str = _SERVICE) -> None:
        super().__init__(level=logging.ERROR)
        self.sender = _Sender(token, url, service)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__:
            return  # falha do próprio envio não vira outro envio
        exc = record.exc_info[1] if record.exc_info else None
        # Uma rota que estoura loga a mesma exceção 3x: `app.app_logs`, a linha 500 do
        # `app.access_logs` e o `uvicorn.error`. Vira 1 incidente: a exceção vai uma vez só,
        # e a linha 500 só vai quando nada da request foi enviado (HTTPException(500) sem log).
        if exc is not None:
            if getattr(exc, "_sentinel_enviada", False):
                return
            try:
                exc._sentinel_enviada = True
            except AttributeError:
                pass  # exceção sem __dict__: cai na trava de repetição
            _excecao_na_request.set(time.monotonic())
        elif record.name == _ACCESS_LOG and time.monotonic() - _excecao_na_request.get() < _MESMA_REQUEST_SECONDS:
            return
        self.sender.submit(
            (record.name, record.funcName, str(record.msg)),
            f"{record.name}:{record.funcName}", exc, record.getMessage(),
        )


_handler: SentinelHandler | None = None


def install(service: str = _SERVICE) -> None:
    """Liga o envio no logger raiz e no `uvicorn.error`, uma vez por processo."""
    global _handler
    token = os.getenv("SENTINEL_INGEST_TOKEN", "").strip()
    if not token:
        logger.info("[sentinel] desligado (SENTINEL_INGEST_TOKEN ausente)")
        return
    if _handler is not None:
        return
    _handler = SentinelHandler(token, service=service)
    logging.getLogger().addHandler(_handler)
    logging.getLogger("uvicorn.error").addHandler(_handler)  # mesma linha 2x: a trava segura
    logger.info("[sentinel] erros do serviço vão pro Sentinel")


def structlog_processor(_logger, method_name: str, event_dict: dict) -> dict:
    """Processor do structlog: error/exception/critical vão pro Sentinel. Vai antes do renderer."""
    if _handler is not None and method_name in ("error", "exception", "critical"):
        event = str(event_dict.get("event", ""))
        exc = sys.exc_info()[1] if method_name == "exception" or event_dict.get("exc_info") else None
        _handler.sender.submit(("structlog", event), event[:200], exc, event)
    return event_dict
