from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

log = logging.getLogger("studious.http")


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Reads or generates X-Correlation-ID, stores it in a context var,
    logs request timing, and echoes the header back on the response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex[:16]
        token = correlation_id_var.set(cid)
        t0 = time.monotonic()

        try:
            log.info(
                "request_start",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            response = await call_next(request)
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "request_end",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            response.headers["x-correlation-id"] = cid
            return response
        finally:
            correlation_id_var.reset(token)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Refuse request bodies over ``max_bytes`` with 413.

    A declared Content-Length over the limit is refused before any of the
    body is read. A body with no declared length (chunked) is counted as it
    arrives and cut off at the limit, so an upload can never fill the disk
    through the multipart spool file. ``max_bytes`` of 0 means no limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(scope, receive, send, int(declared))
            return

        received = 0
        response_started = False

        def over() -> bool:
            return received > self.max_bytes

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if over():
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            # Once the limit is crossed, whatever the app says about the
            # aborted read (FastAPI turns it into a 400 "error parsing the
            # body") is dropped in favour of the 413 below.
            if over() and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not over() or response_started:
                raise
        if over() and not response_started:
            await self._refuse(scope, receive, send, received)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, size: int) -> None:
        limit_mb = self.max_bytes / (1024 * 1024)
        log.warning(
            "request_body_too_large",
            extra={"method": scope["method"], "path": scope["path"], "bytes": size, "limit_bytes": self.max_bytes},
        )
        response = JSONResponse(
            status_code=413,
            content={
                "detail": f"upload is larger than the {limit_mb:g} MB limit "
                "(STUDIOUS_UPLOAD_MAX_MB raises it)"
            },
        )
        await response(scope, receive, send)


# Attributes set by stdlib's `logging.LogRecord` — anything not in this set
# is treated as caller-supplied via `extra={...}` and merged into the JSON.
_STDLIB_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


class StructuredFormatter(logging.Formatter):
    """Emits log records as single-line JSON with correlation ID.

    All caller-supplied `extra={...}` fields are preserved; only the stdlib
    `LogRecord` attributes (and a few formatter-injected ones) are filtered
    out. Add a new field to a log site by passing it in `extra=` — no change
    to this formatter is needed.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(""),
        }
        for key, val in record.__dict__.items():
            if key in _STDLIB_RECORD_ATTRS or key in entry:
                continue
            entry[key] = val
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)
