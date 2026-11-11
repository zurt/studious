from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import store

client = TestClient(app)


def _seed_active(headword="口べた", reading="くちべた"):
    store.replace_region_sightings(
        "vocab",
        doc_id="d1",
        chapter_id="c1",
        region_id=f"r-{headword}",
        source="breakdown",
        entries=[
            {
                "headword": headword,
                "reading": reading,
                "meaning": "poor speaker",
                "sentence_index": 0,
                "surface": headword,
                "sentence_text": "口べたで料理好きの父親。",
            }
        ],
    )
    item_id = store.build_index("vocab")[store.vocab_key(headword, reading)]
    store.update_item("vocab", item_id, status="active")
    return item_id


class TestQueue:
    def test_empty_queue(self, isolated_data_dir: Path):
        r = client.get("/api/study/queue")
        assert r.status_code == 200
        assert r.json() == {
            "cards": [],
            "counts": {"due": 0, "new": 0, "active_items": 0},
        }

    def test_queue_serves_active_cards(self, isolated_data_dir: Path):
        item_id = _seed_active()
        data = client.get("/api/study/queue").json()
        assert data["counts"]["new"] == 2
        card = data["cards"][0]
        assert card["item_id"] == item_id
        assert card["kind"] == "vocab"
        assert card["item"]["headword"] == "口べた"
        assert card["state"]["reps"] == 0


class TestReviews:
    def test_review_roundtrip(self, isolated_data_dir: Path):
        item_id = _seed_active()
        r = client.post(
            "/api/study/reviews",
            json={
                "kind": "vocab",
                "item_id": item_id,
                "card_type": "word",
                "grade": 3,
                "elapsed_ms": 2100,
            },
        )
        assert r.status_code == 201
        state = r.json()["state"]
        assert state["reps"] == 1
        assert state["due"] is not None
        # The graded word card leaves the new pool; the context card remains.
        data = client.get("/api/study/queue").json()
        assert data["counts"]["new"] == 1
        assert [c["card_type"] for c in data["cards"]] == ["context"]

    def test_failed_card_gets_relearn_due(self, isolated_data_dir: Path):
        item_id = _seed_active()
        r = client.post(
            "/api/study/reviews",
            json={"kind": "vocab", "item_id": item_id, "card_type": "word", "grade": 1},
        )
        assert r.status_code == 201
        assert r.json()["state"]["lapses"] == 1

    def test_unknown_item_404(self, isolated_data_dir: Path):
        r = client.post(
            "/api/study/reviews",
            json={"kind": "vocab", "item_id": "missing", "card_type": "word", "grade": 3},
        )
        assert r.status_code == 404

    def test_bad_kind_404_and_bad_inputs_400(self, isolated_data_dir: Path):
        item_id = _seed_active()
        assert (
            client.post(
                "/api/study/reviews",
                json={"kind": "bogus", "item_id": item_id, "card_type": "word", "grade": 3},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/study/reviews",
                json={"kind": "vocab", "item_id": item_id, "card_type": "nope", "grade": 3},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/study/reviews",
                json={"kind": "vocab", "item_id": item_id, "card_type": "word", "grade": 9},
            ).status_code
            == 400
        )

    def test_deleted_item_404(self, isolated_data_dir: Path):
        item_id = _seed_active()
        store.delete_item("vocab", item_id)
        r = client.post(
            "/api/study/reviews",
            json={"kind": "vocab", "item_id": item_id, "card_type": "word", "grade": 3},
        )
        assert r.status_code == 404
