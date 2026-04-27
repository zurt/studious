from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chapters, documents, jobs, providers, regions, transcribe
from .jobs import manager
from .middleware import CorrelationMiddleware, StructuredFormatter
from .providers import registry

# Structured JSON logging
_handler = logging.StreamHandler()
_handler.setFormatter(StructuredFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])


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


@app.get("/api/health")
def health():
    return {"ok": True}
