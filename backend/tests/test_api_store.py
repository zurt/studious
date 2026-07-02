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


class TestMergeEndpoint:
    def _dupes(self):
        _seed()
        _seed(headword="口下手", surface="口下手", region_id="r2")
        items = {i["headword"]: i for i in client.get("/api/vocab").json()["items"]}
        return items["口べた"], items["口下手"]

    def test_merge_vocab(self, isolated_data_dir: Path):
        target, source = self._dupes()
        r = client.post(
            f"/api/vocab/{target['id']}/merge", json={"source_id": source["id"]}
        )
        assert r.status_code == 200
        merged = r.json()
        assert len(merged["sightings"]) == 2
        assert client.get("/api/vocab").json()["total"] == 1

    def test_merged_variant_searchable(self, isolated_data_dir: Path):
        target, source = self._dupes()
        client.post(f"/api/vocab/{target['id']}/merge", json={"source_id": source["id"]})
        assert client.get("/api/vocab", params={"q": "口下手"}).json()["total"] == 1

    def test_merge_missing_404(self, isolated_data_dir: Path):
        target, _ = self._dupes()
        r = client.post(f"/api/vocab/{target['id']}/merge", json={"source_id": "nope"})
        assert r.status_code == 404

    def test_merge_self_400(self, isolated_data_dir: Path):
        target, _ = self._dupes()
        r = client.post(
            f"/api/vocab/{target['id']}/merge", json={"source_id": target["id"]}
        )
        assert r.status_code == 400

    def test_merge_grammar(self, isolated_data_dir: Path):
        a = client.post("/api/grammar", json={"pattern": "〜ようになる"}).json()
        b = client.post("/api/grammar", json={"pattern": "ようになった形"}).json()
        r = client.post(f"/api/grammar/{a['id']}/merge", json={"source_id": b["id"]})
        assert r.status_code == 200
        assert client.get("/api/grammar").json()["total"] == 1


class TestVocabLookup:
    def test_lookup_matches_and_misses(self, isolated_data_dir: Path):
        _seed()
        r = client.post(
            "/api/vocab/lookup",
            json={
                "entries": [
                    {"headword": "口べた", "reading": "くちべた"},
                    {"headword": "存在しない", "reading": "そんざいしない"},
                ]
            },
        )
        assert r.status_code == 200
        matches = r.json()["matches"]
        assert matches[0]["status"] == "unreviewed"
        assert matches[1] is None

    def test_lookup_matches_merged_variant(self, isolated_data_dir: Path):
        _seed()
        _seed(headword="口下手", surface="口下手", region_id="r2")
        items = {i["headword"]: i for i in client.get("/api/vocab").json()["items"]}
        client.post(
            f"/api/vocab/{items['口べた']['id']}/merge",
            json={"source_id": items["口下手"]["id"]},
        )
        r = client.post(
            "/api/vocab/lookup",
            json={"entries": [{"headword": "口下手", "reading": "くちべた"}]},
        )
        assert r.json()["matches"][0]["id"] == items["口べた"]["id"]


class TestCoverage:
    def test_chapter_coverage_counts(self, isolated_data_dir: Path):
        _seed()
        _seed(headword="犬", reading="いぬ", meaning="dog", region_id="r2")
        item = client.get("/api/vocab", params={"q": "犬"}).json()["items"][0]
        client.patch(f"/api/vocab/{item['id']}", json={"status": "known"})
        r = client.get("/api/store/coverage", params={"chapter_id": "c1"})
        assert r.status_code == 200
        cov = r.json()
        assert cov["vocab"]["total"] == 2
        assert cov["vocab"]["known"] == 1
        assert cov["vocab"]["unreviewed"] == 1
        assert cov["grammar"]["total"] == 0

    def test_coverage_other_chapter_empty(self, isolated_data_dir: Path):
        _seed()
        cov = client.get("/api/store/coverage", params={"chapter_id": "cX"}).json()
        assert cov["vocab"]["total"] == 0
