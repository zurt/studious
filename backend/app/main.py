from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import documents, jobs, providers, transcribe
from .jobs import manager
from .providers import registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.bootstrap_default_providers()
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Studious", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(transcribe.router)
app.include_router(jobs.router)
app.include_router(providers.router)


@app.get("/api/health")
def health():
    return {"ok": True}
