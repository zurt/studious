from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import enrich, store, wanikani

client = TestClient(app)


def _subject(sid: int, obj: str, characters: str, level: int, components: list[int] | None = None, **data: Any):
    return {
        "id": sid,
        "object": obj,
        "url": f"https://api.wanikani.com/v2/subjects/{sid}",
        "data_updated_at": f"2026-06-0{min(sid % 9 + 1, 9)}T00:00:00Z",
        "data": {
            "characters": characters,
            "slug": characters,
            "level": level,
            "document_url": f"https://www.wanikani.com/{obj}/{characters}",
            "meanings": [{"meaning": f"meaning-{sid}", "primary": True}],
            "readings": [{"reading": f"reading-{sid}", "primary": True}] if obj != "radical" else [],
            "meaning_mnemonic": f"mnemonic-{sid}",
            "reading_mnemonic": f"reading-mnemonic-{sid}" if obj != "radical" else "",
            "component_subject_ids": components or [],
            "hidden_at": None,
            **data,
        },
    }


SUBJECTS = [
    _subject(50, "radical", "力", 1),
    _subject(51, "radical", "弓", 1),
    _subject(700, "kanji", "勉", 4, components=[50]),
    _subject(701, "kanji", "強", 4, components=[51]),
    _subject(2467, "vocabulary", "勉強", 4, components=[700, 701]),
]

STUDY_MATERIALS = [
    {
        "id": 9001,
        "object": "study_material",
        "data_updated_at": "2026-06-05T00:00:00Z",
        "data": {
            "subject_id": 700,
            "meaning_note": "my 勉 note",
            "reading_note": "",
            "meaning_synonyms": ["effort"],
        },
    }
]

ASSIGNMENTS = [
    {
        "id": 8001,
        "object": "assignment",
        "data_updated_at": "2026-06-06T00:00:00Z",
        "data": {
            "subject_id": 2467,
            "srs_stage": 9,
            "burned_at": "2022-11-03T00:00:00Z",
            "passed_at": "2022-01-01T00:00:00Z",
        },
    }
]


@pytest.fixture
def wk_env(isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WANIKANI_API_TOKEN", "wk-test-token")
    from app import config

    config.get_settings.cache_clear()

    calls: list[str] = []

    def fake_fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        # Two-page subjects collection to exercise pagination.
        if "/subjects" in url and "page2" not in url:
            return {
                "pages": {"next_url": "https://api.wanikani.com/v2/subjects?page2=1"},
                "data": SUBJECTS[:3],
            }
        if "page2" in url:
            return {"pages": {"next_url": None}, "data": SUBJECTS[3:]}
        if "/study_materials" in url:
            return {"pages": {"next_url": None}, "data": STUDY_MATERIALS}
        if "/assignments" in url:
            return {"pages": {"next_url": None}, "data": ASSIGNMENTS}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(wanikani, "_fetch_json", fake_fetch)
    return calls


class TestSync:
    def test_full_sync_populates_cache(self, wk_env):
        result = wanikani.sync()
        assert result["fetched"] == {"subjects": 5, "study_materials": 1, "assignments": 1}
        s = wanikani.status()
        assert s["configured"] is True
        assert s["counts"]["subjects"] == 5
        assert wanikani.level_for("勉強") == 4

    def test_incremental_sync_uses_cursor(self, wk_env):
        wanikani.sync()
        wk_env.clear()
        wanikani.sync()
        subject_calls = [u for u in wk_env if "/subjects" in u and "page2" not in u]
        assert subject_calls and "updated_after=" in subject_calls[0]

    def test_resync_latest_wins(self, wk_env):
        wanikani.sync()
        wanikani.sync(full=True)
        assert len(wanikani._load_latest("subjects")) == 5

    def test_sync_without_token_raises(self, isolated_data_dir: Path):
        with pytest.raises(RuntimeError):
            wanikani.sync()


class TestDrilldown:
    def test_assembles_component_graph(self, wk_env):
        wanikani.sync()
        d = wanikani.drilldown("勉強")
        assert d is not None
        assert d["level"] == 4
        assert d["meaning_mnemonic"] == "mnemonic-2467"
        # Burned SRS from years ago — display only.
        assert d["srs"]["stage_name"] == "burned"
        assert d["srs"]["burned_at"] == "2022-11-03T00:00:00Z"
        assert [k["characters"] for k in d["kanji"]] == ["勉", "強"]
        ben = d["kanji"][0]
        assert ben["user_notes"]["meaning_note"] == "my 勉 note"
        assert [r["characters"] for r in ben["radicals"]] == ["力"]

    def test_miss_returns_none(self, wk_env):
        wanikani.sync()
        assert wanikani.drilldown("存在しない") is None


class TestEnrichIntegration:
    def _seed(self):
        store.replace_region_sightings(
            "vocab",
            doc_id="d1",
            chapter_id="c1",
            region_id="r1",
            source="breakdown",
            entries=[
                {
                    "headword": "勉強",
                    "reading": "べんきょう",
                    "meaning": "study",
                    "sentence_index": 0,
                    "surface": "勉強",
                    "sentence_text": "",
                }
            ],
        )

    def test_wk_level_and_link_in_classifications(self, wk_env):
        wanikani.sync()
        self._seed()
        result = enrich.enrich_pending()
        assert result["attempted"] == 1
        item = store.list_items("vocab")[0]
        assert item["classifications"]["wanikani_level"] == 4
        assert item["links"]["wanikani"] == "https://www.wanikani.com/vocabulary/勉強"
        # WK burned status must NOT touch the curation status.
        assert item["status"] == "unreviewed"

    def test_srs_never_marks_known(self, wk_env):
        wanikani.sync()
        self._seed()
        enrich.enrich_pending()
        item = store.list_items("vocab")[0]
        assert item["status"] == "unreviewed"
        assert "wanikani_srs" not in item["classifications"]


class TestApi:
    def test_status_endpoint(self, wk_env):
        r = client.get("/api/refs/wanikani/status")
        assert r.status_code == 200
        assert r.json()["configured"] is True

    def test_sync_endpoint_409_without_token(self, isolated_data_dir: Path):
        assert client.post("/api/refs/wanikani/sync").status_code == 409

    def test_sync_endpoint_runs_and_enriches(self, wk_env):
        r = client.post("/api/refs/wanikani/sync")
        assert r.status_code == 200
        body = r.json()
        assert body["fetched"]["subjects"] == 5
        assert "enriched" in body

    def test_drilldown_endpoint(self, wk_env):
        wanikani.sync()
        TestEnrichIntegration()._seed()
        item = client.get("/api/vocab").json()["items"][0]
        r = client.get(f"/api/vocab/{item['id']}/wanikani")
        assert r.status_code == 200
        assert r.json()["characters"] == "勉強"
        # Unknown word → 404 from the drilldown, not a crash.
        other = client.post("/api/vocab", json={"headword": "珍しい語", "reading": "めずらしいご"}).json()
        assert client.get(f"/api/vocab/{other['id']}/wanikani").status_code == 404

    def test_drilldown_endpoint_409_when_cache_empty(self, isolated_data_dir: Path):
        item = client.post("/api/vocab", json={"headword": "勉強", "reading": "べんきょう"}).json()
        assert client.get(f"/api/vocab/{item['id']}/wanikani").status_code == 409
