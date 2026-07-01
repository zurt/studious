from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import store

client = TestClient(app)


def _seed(region_id="r1", source="breakdown", **entry_over):
    entry = {
        "headword": "口べた",
        "reading": "くちべた",
        "meaning": "poor speaker",
        "sentence_index": 0,
        "surface": "口べた",
        "sentence_text": "口べたで料理好きの父親。",
    }
    entry.update(entry_over)
    store.replace_region_sightings(
        "vocab",
        doc_id="d1",
        chapter_id="c1",
        region_id=region_id,
        source=source,
        entries=[entry],
    )


class TestListVocab:
    def test_lists_items(self, isolated_data_dir: Path):
        _seed()
        r = client.get("/api/vocab")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["headword"] == "口べた"

    def test_status_filter(self, isolated_data_dir: Path):
        _seed()
        _seed(headword="犬", reading="いぬ", meaning="dog")
        item = client.get("/api/vocab", params={"q": "犬"}).json()["items"][0]
        client.patch(f"/api/vocab/{item['id']}", json={"status": "known"})
        assert client.get("/api/vocab", params={"status": "known"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"status": "unreviewed"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"status": "bogus"}).status_code == 400

    def test_search_matches_reading_and_meaning(self, isolated_data_dir: Path):
        _seed()
        assert client.get("/api/vocab", params={"q": "くちべた"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"q": "POOR"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"q": "nothing"}).json()["total"] == 0

    def test_doc_chapter_source_filters(self, isolated_data_dir: Path):
        _seed()
        assert client.get("/api/vocab", params={"doc_id": "d1"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"doc_id": "dX"}).json()["total"] == 0
        assert client.get("/api/vocab", params={"chapter_id": "c1"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"source": "breakdown"}).json()["total"] == 1
        assert client.get("/api/vocab", params={"source": "vocab_list"}).json()["total"] == 0
        assert client.get("/api/vocab", params={"source": "bogus"}).status_code == 400

    def test_alpha_sort_and_pagination(self, isolated_data_dir: Path):
        _seed(headword="猫", reading="ねこ", meaning="cat")
        _seed(headword="犬", reading="いぬ", meaning="dog", region_id="r2")
        data = client.get("/api/vocab", params={"sort": "alpha"}).json()
        assert [i["headword"] for i in data["items"]] == ["犬", "猫"]
        page = client.get("/api/vocab", params={"sort": "alpha", "limit": 1, "offset": 1}).json()
        assert page["total"] == 2
        assert [i["headword"] for i in page["items"]] == ["猫"]


class TestVocabCrud:
    def test_manual_create_defaults_active(self, isolated_data_dir: Path):
        r = client.post(
            "/api/vocab",
            json={"headword": "勉強", "reading": "ベンキョウ", "meaning": "study"},
        )
        assert r.status_code == 201
        item = r.json()
        assert item["status"] == "active"
        assert item["reading"] == "べんきょう"  # normalized to hiragana

    def test_create_duplicate_conflicts(self, isolated_data_dir: Path):
        client.post("/api/vocab", json={"headword": "勉強", "reading": "べんきょう"})
        r = client.post("/api/vocab", json={"headword": "勉強", "reading": "べんきょう"})
        assert r.status_code == 409

    def test_create_blank_headword_rejected(self, isolated_data_dir: Path):
        assert client.post("/api/vocab", json={"headword": "  "}).status_code == 400

    def test_patch_status_and_notes(self, isolated_data_dir: Path):
        _seed()
        item = client.get("/api/vocab").json()["items"][0]
        r = client.patch(
            f"/api/vocab/{item['id']}", json={"status": "active", "notes": "n"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "active"
        assert r.json()["notes"] == "n"

    def test_patch_missing_404(self, isolated_data_dir: Path):
        assert client.patch("/api/vocab/nope", json={"status": "known"}).status_code == 404

    def test_patch_empty_body_400(self, isolated_data_dir: Path):
        _seed()
        item = client.get("/api/vocab").json()["items"][0]
        assert client.patch(f"/api/vocab/{item['id']}", json={}).status_code == 400

    def test_delete_tombstones_and_hides(self, isolated_data_dir: Path):
        _seed()
        item = client.get("/api/vocab").json()["items"][0]
        assert client.delete(f"/api/vocab/{item['id']}").status_code == 200
        assert client.get("/api/vocab").json()["total"] == 0
        assert client.delete(f"/api/vocab/{item['id']}").status_code == 404


class TestGrammar:
    def test_grammar_crud_roundtrip(self, isolated_data_dir: Path):
        r = client.post(
            "/api/grammar",
            json={"pattern": "〜に関わらず", "explanation": "regardless of"},
        )
        assert r.status_code == 201
        item = r.json()
        assert item["pattern_normalized"] == "に関わらず"
        # Tilde-less variant is the same pattern.
        assert (
            client.post("/api/grammar", json={"pattern": "に関わらず"}).status_code == 409
        )
        r = client.patch(f"/api/grammar/{item['id']}", json={"status": "known"})
        assert r.status_code == 200
        listed = client.get("/api/grammar", params={"status": "known"}).json()
        assert listed["total"] == 1


class TestStoreOps:
    def test_stats(self, isolated_data_dir: Path):
        _seed()
        client.post("/api/grammar", json={"pattern": "〜てもらう"})
        s = client.get("/api/store/stats").json()
        assert s["vocab"]["total"] == 1
        assert s["vocab"]["unreviewed"] == 1
        assert s["grammar"]["active"] == 1

    def test_backfill_empty_data(self, isolated_data_dir: Path):
        r = client.post("/api/store/backfill")
        assert r.status_code == 200
        assert r.json()["vocab_list_regions"] == 0
