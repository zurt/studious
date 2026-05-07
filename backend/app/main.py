from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chapters, costs, documents, jobs, providers, regions, transcribe
from .config import get_settings
from .jobs import manager
from .middleware import CorrelationMiddleware, StructuredFormatter
from .providers import registry

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
app.include_router(costs.router)


@app.get("/api/health")
def health():
    return {"ok": True}
