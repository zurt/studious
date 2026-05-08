from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.api.jobs import job_events
from app.jobs import manager
from app.main import app
from app.services import storage


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


def test_get_job_404(client):
    r = client.get("/api/jobs/missing")
    assert r.status_code == 404


def test_get_job_returns_payload(client):
    job = storage.create_job({"engine": "ocr", "provider": "tesseract"})
    r = client.get(f"/api/jobs/{job['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == job["id"]


def test_job_events_404_for_unknown(client):
    r = client.get("/api/jobs/missing/events")
    assert r.status_code == 404


async def test_job_events_snapshot_and_terminal(isolated_data_dir):
    """Drive the SSE generator directly: it replays the persisted snapshot
    first, then closes on a terminal `job-done` event."""
    job = storage.create_job({"engine": "ocr", "provider": "x", "pages": [1]})
    storage.update_job(job["id"], status="completed", finished_at="now", errors=[])

    class _FakeRequest:
        async def is_disconnected(self):
            return False

    response = await job_events(job["id"], _FakeRequest())
    gen = response.body_iterator

    first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert first["event"] == "snapshot"
    snap = json.loads(first["data"])
    assert snap["id"] == job["id"]
    assert snap["status"] == "completed"

    # Listener was registered when the request handler ran.
    assert manager._listeners.get(job["id"])
    manager._emit(job["id"], {"event": "job-done", "data": {"errors": []}})

    second = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert second["event"] == "job-done"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    # `unsubscribe` runs in the generator's `finally`.
    assert job["id"] not in manager._listeners
