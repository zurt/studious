"""STUDIOUS_STATIC_DIR (serve the built frontend) and STUDIOUS_CORS_ORIGINS."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import create_app


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("STUDIOUS_STATIC_DIR", raising=False)
    monkeypatch.delenv("STUDIOUS_CORS_ORIGINS", raising=False)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>shell</title>")
    (d / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    return d


def _client(monkeypatch, static_dir=None, cors=None) -> TestClient:
    if static_dir is not None:
        monkeypatch.setenv("STUDIOUS_STATIC_DIR", str(static_dir))
    if cors is not None:
        monkeypatch.setenv("STUDIOUS_CORS_ORIGINS", cors)
    config.get_settings.cache_clear()
    return TestClient(create_app())


def test_unset_serves_no_frontend(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/").status_code == 404
    assert c.get("/api/health").json() == {"ok": True}


def test_missing_directory_is_ignored(monkeypatch, tmp_path):
    c = _client(monkeypatch, static_dir=tmp_path / "nope")
    assert config.get_settings().static_dir is None
    assert c.get("/").status_code == 404


def test_directory_without_index_is_ignored(monkeypatch, tmp_path):
    (tmp_path / "empty").mkdir()
    c = _client(monkeypatch, static_dir=tmp_path / "empty")
    assert c.get("/").status_code == 404


def test_serves_index_at_root(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    r = c.get("/")
    assert r.status_code == 200
    assert "<title>shell</title>" in r.text


def test_serves_static_assets(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    r = c.get("/assets/app.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"


def test_spa_fallback_for_deep_links(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    for path in ("/vocab", "/documents/abc/chapters/1", "/assets/missing.js"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "<title>shell</title>" in r.text


def test_api_routes_win_over_the_fallback(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    assert c.get("/api/health").json() == {"ok": True}
    assert c.get("/api/providers").headers["content-type"].startswith("application/json")


def test_unknown_api_path_is_a_json_404(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    for path in ("/api/nope", "/api/documents/x/nope/deeper", "/api"):
        r = c.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json")
        assert "shell" not in r.text


def test_path_traversal_does_not_leave_the_directory(monkeypatch, dist):
    c = _client(monkeypatch, static_dir=dist)
    assert "outside" not in c.get("/%2e%2e/secret.txt").text
    assert "outside" not in c.get("/..%2fsecret.txt").text


def _preflight(c: TestClient, origin: str):
    return c.options(
        "/api/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_cors_default_is_the_vite_origin(monkeypatch):
    assert config.get_settings().cors_origins == ["http://localhost:5173"]
    c = _client(monkeypatch)
    assert _preflight(c, "http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in _preflight(c, "https://other.example").headers


def test_cors_origins_are_a_comma_separated_allowlist(monkeypatch):
    c = _client(monkeypatch, cors=" https://a.example , https://b.example,, ")
    assert config.get_settings().cors_origins == ["https://a.example", "https://b.example"]
    assert _preflight(c, "https://b.example").headers.get("access-control-allow-origin") == "https://b.example"
    assert "access-control-allow-origin" not in _preflight(c, "http://localhost:5173").headers


def test_blank_cors_value_keeps_the_default(monkeypatch):
    _client(monkeypatch, cors=" , ")
    assert config.get_settings().cors_origins == ["http://localhost:5173"]
