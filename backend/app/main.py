from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

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
from .services import enrich, speech_queue
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
    # Card clips still missing (the Mac was asleep) are retried on a timer.
    speech_task = asyncio.create_task(speech_queue.periodic())
    try:
        yield
    finally:
        enrich_task.cancel()
        speech_task.cancel()
        await manager.stop()


def _mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend at `/`, falling back to index.html for SPA
    routes. Registered after every API route, so `/api/*` always wins; an
    unknown `/api/...` path stays a JSON 404 rather than the HTML shell."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Studious", lifespan=lifespan)
    app.add_middleware(CorrelationMiddleware)

    @app.exception_handler(InvalidIdError)
    async def invalid_id_handler(request: Request, exc: InvalidIdError):
        # Path-unsafe resource ids (e.g. `..`) must never reach the filesystem;
        # to the client they are indistinguishable from a missing resource.
        return JSONResponse(status_code=404, content={"detail": "not found"})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-correlation-id"],
    )

    for module in (
        documents,
        chapters,
        regions,
        transcribe,
        jobs,
        providers,
        preferences,
        costs,
        store,
        anki,
        study,
    ):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    if settings.static_dir is not None and (settings.static_dir / "index.html").is_file():
        _mount_frontend(app, settings.static_dir)
    return app


app = create_app()
