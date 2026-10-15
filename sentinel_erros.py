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
