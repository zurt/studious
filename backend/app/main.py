from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    anki,
    chapters,
    costs,
    documents,
    jobs,
    preferences,
    providers,
    regions,
    store,
    study,
    transcribe,
)
from .config import get_settings
from .jobs import manager
from .middleware import CorrelationMiddleware, StructuredFormatter
from .providers import registry
from .services import enrich
from .services.storage import InvalidIdError

# Structured JSON logging. Level is configurable via STUDIOUS_LOG_LEVEL.
_handler = logging.StreamHandler()
_handler.setFormatter(StructuredFormatter())
_level = logging.getLevelName(get_settings().log_level)
logging.basicConfig(
    level=_level if isinstance(_level, int) else logging.INFO,
    handlers=[_handler],
)


async def _enrich_in_background() -> None:
    log = logging.getLogger("studious.main")
    start = time.monotonic()
    log.info("startup_enrich_start")
    try:
        result = await asyncio.to_thread(enrich.enrich_pending)
        log.info(
            "startup_enrich_done",
            extra={**result, "seconds": round(time.monotonic() - start, 2)},
        )
    except Exception:  # noqa: BLE001 - enrichment is best-effort at startup
        log.exception("startup_enrich_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.bootstrap_default_providers()
    await manager.start()
    # Items enriched before a reference index was (re)built pick up new fields
    # here; a no-op when nothing is pending.
    enrich_task = asyncio.create_task(_enrich_in_background())
    try:
        yield
    finally:
        enrich_task.cancel()
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
app.include_router(anki.router)
app.include_router(study.router)


@app.get("/api/health")
def health():
    return {"ok": True}
