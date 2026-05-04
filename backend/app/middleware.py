from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
