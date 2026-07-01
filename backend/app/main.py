from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    chapters,
    costs,
    documents,
    jobs,
    preferences,
    providers,
    regions,
    store,
    transcribe,
)
from .config import get_settings
from .jobs import manager
from .middleware import CorrelationMiddleware, StructuredFormatter
from .providers import registry
from .services.storage import InvalidIdError

# Structured JSON logging. Level is configurable via STUDIOUS_LOG_LEVEL.
_handler = logging.StreamHandler()
_handler.setFormatter(StructuredFormatter())
_level = logging.getLevelName(get_settings().log_level)
logging.basicConfig(
    level=_level if isinstance(_level, int) else logging.INFO,
    handlers=[_handler],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.bootstrap_default_providers()
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Studious", lifespan=lifespan)
app.add_middleware(CorrelationMiddleware)


@app.exception_handler(InvalidIdError)
async def invalid_id_handler(request: Request, exc: InvalidIdError):
    # Path-unsafe resource ids (e.g. `..`) must never reach the filesystem;
    # to the client they are indistinguishable from a missing resource.
    return JSONResponse(status_code=404, content={"detail": "not found"})
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-correlation-id"],
)

app.include_router(documents.router)
app.include_router(chapters.router)
app.include_router(regions.router)
app.include_router(transcribe.router)
app.include_router(jobs.router)
app.include_router(providers.router)
app.include_router(preferences.router)
app.include_router(costs.router)
app.include_router(store.router)


@app.get("/api/health")
def health():
    return {"ok": True}
