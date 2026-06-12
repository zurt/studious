"""Path-unsafe resource ids must never reach the filesystem.

Resource ids (doc/chapter/region/job) come straight from URL path segments,
and storage interpolates them into filesystem paths. Anything containing
`.` or a path separator could escape the data directory — e.g.
`DELETE /api/documents/..` would have rmtree'd the whole data dir.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import storage
from app.services.storage import InvalidIdError

TRAVERSAL_IDS = ["..", "../..", "a/../b", "a\\b", ".", "x.json", "", "a" * 65]


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_document_dir_rejects_unsafe_ids(isolated_data_dir, bad_id):
    with pytest.raises(InvalidIdError):
        storage.document_dir(bad_id)


@pytest.mark.parametrize("bad_id", TRAVERSAL_IDS)
def test_load_document_rejects_unsafe_ids(isolated_data_dir, bad_id):
    with pytest.raises(InvalidIdError):
        storage.load_document(bad_id)


def test_chapter_region_job_paths_reject_unsafe_ids(isolated_data_dir):
    with pytest.raises(InvalidIdError):
        storage.load_chapter("abcdef123456", "..")
    with pytest.raises(InvalidIdError):
        storage.load_region("abcdef123456", "abcdef123456", "../../meta")
    with pytest.raises(InvalidIdError):
        storage.breakdown_path("abcdef123456", "abcdef123456", "..")
    with pytest.raises(InvalidIdError):
        storage.exercise_completion_path("abcdef123456", "abcdef123456", "..")
    with pytest.raises(InvalidIdError):
        storage.load_job("../documents/x")


def test_valid_ids_still_pass(isolated_data_dir):
    # Generated ids are 12-char hex, but historical or test ids may be any
    # alphanumeric/underscore/hyphen string.
    assert storage.load_document("abcdef123456") is None
    assert storage.load_document("not-a-real_ID") is None
    assert storage.load_job("does-not-exist") is None


def test_api_maps_invalid_id_to_404(client):
    # %2e%2e decodes to `..` in the path segment before routing.
    r = client.delete("/api/documents/%2e%2e")
    assert r.status_code == 404
    r = client.get("/api/documents/%2e%2e")
    assert r.status_code == 404


def test_delete_with_traversal_id_does_not_touch_data_dir(client, isolated_data_dir):
    # The documents root itself must survive a traversal attempt.
    docs_root = isolated_data_dir / "documents"
    docs_root.mkdir(exist_ok=True)
    sentinel = docs_root / "sentinel.txt"
    sentinel.write_text("still here")
    client.delete("/api/documents/%2e%2e")
    assert docs_root.exists()
    assert sentinel.read_text() == "still here"
