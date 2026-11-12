from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import enrich, freq, jmdict, refs_build, store
from tests.test_enrich import _seed_vocab, built_db  # noqa: F401 - fixture

client = TestClient(app)

INDEX = {"title": "JPDB", "format": 3, "frequencyMode": "rank-based", "revision": "rev-A"}


def _kanji(term, reading, value, kana=False, display=None):
    shown = display or (f"{value}㋕" if kana else str(value))
    return [term, "freq", {"reading": reading, "frequency": {"value": value, "displayValue": shown}}]


def _kana(term, value, display=None):
    return [term, "freq", {"value": value, "displayValue": display or f"{value}㋕"}]


BANK = [
    _kanji("嬉しい", "うれしい", 355),
    _kanji("嬉しい", "うれしい", 1668, kana=True),  # kana-form rank: must not rank the kanji spelling
    _kana("うれしい", 1668),
    _kanji("市場", "いちば", 4000),
    _kanji("市場", "しじょう", 900),
    _kana("なる", 15),
    _kana("なる", 3814),  # homograph: the most frequent wins
    _kana("ダミー", 183459, "183459❌"),  # not in corpus: placeholder, skipped
    _kanji("幻", "まぼろし", 183459, display="183459❌"),
    ["bad"],  # malformed rows are skipped, not fatal
    ["x", "freq", {"value": "NaN"}],
    ["y", "ipa", {"value": 3}],
]


def make_zip(path: Path, members: dict[str, bytes | str] | None = None, bank=BANK, index=INDEX) -> Path:
    if members is None:
        members = {
            "index.json": json.dumps(index),
            "term_meta_bank_1.json": json.dumps(bank, ensure_ascii=False),
        }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def freq_db(isolated_data_dir, tmp_path):
    freq.close()
    refs_build.build_freq_sqlite(make_zip(tmp_path / "f.zip"), refs_build.freq_db_path(), version="v1")
    yield refs_build.freq_db_path()
    freq.close()


class TestBuild:
    def test_rows_and_meta(self, freq_db):
        meta = freq.meta()
        assert meta["version"] == "v1" and meta["revision"] == "rev-A"
        assert freq.revision() == "rev-A"
        # 嬉しい(355), うれしい(1668), 市場 x2, なる(min): no rows for the
        # placeholder, kana-form or malformed entries.
        assert meta["rows"] == "5"

    def test_ignored_rows_are_not_ranked(self, freq_db):
        assert freq.lookup("ダミー") is None
        assert freq.lookup("幻", "まぼろし") is None
        assert freq.lookup("x") is None and freq.lookup("y") is None


class TestLookup:
    def test_prefers_item_spelling(self, freq_db):
        assert freq.lookup("嬉しい", "うれしい") == 355  # kanji spelling
        assert freq.lookup("うれしい", "うれしい") == 1668  # kana spelling

    def test_reading_picks_homograph_then_falls_back_to_word(self, freq_db):
        assert freq.lookup("市場", "しじょう") == 900
        assert freq.lookup("市場", "イチバ") == 4000  # katakana reading normalised
        assert freq.lookup("市場", "ちがう") == 900  # reading mismatch: word alone, best rank
        assert freq.lookup("市場") == 900

    def test_kana_homograph_takes_most_frequent(self, freq_db):
        assert freq.lookup("なる", "なる") == 15

    def test_unavailable(self, isolated_data_dir):
        freq.close()
        assert freq.is_available() is False
        assert freq.lookup("嬉しい", "うれしい") is None
        assert freq.revision() is None

    def test_reopens_after_rebuild(self, freq_db, tmp_path):
        assert freq.lookup("なる", "なる") == 15
        refs_build.build_freq_sqlite(
            make_zip(tmp_path / "g.zip", bank=[_kana("なる", 7)], index={**INDEX, "revision": "rev-B"}),
            refs_build.freq_db_path(),
            version="v2",
        )
        assert freq.lookup("なる", "なる") == 7
        assert freq.revision() == "rev-B"


class TestZipGuards:
    def _build(self, tmp_path, members):
        return refs_build.build_freq_sqlite(
            make_zip(tmp_path / "z.zip", members), tmp_path / "out.sqlite", version="v"
        )

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="unsafe zip member"):
            self._build(tmp_path, {"index.json": json.dumps(INDEX), "../evil.json": "[]"})
        assert not (tmp_path / "out.sqlite").exists()

    def test_absolute_and_backslash_names_rejected(self, tmp_path):
        for name in ("/etc/x.json", "a\\b.json", "sub/../x.json"):
            with pytest.raises(ValueError, match="unsafe zip member"):
                self._build(tmp_path, {"index.json": json.dumps(INDEX), name: "[]"})

    def test_nothing_is_extracted(self, tmp_path):
        self._build(
            tmp_path,
            {"index.json": json.dumps(INDEX), "term_meta_bank_1.json": "[]", "payload.py": "raise SystemExit"},
        )
        assert {p.name for p in tmp_path.iterdir()} == {"out.sqlite", "z.zip"}

    def test_oversized_member_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(refs_build, "FREQ_MAX_MEMBER_BYTES", 50)
        members = {"index.json": json.dumps(INDEX), "term_meta_bank_1.json": "[" + " " * 100 + "]"}
        with pytest.raises(ValueError, match="too large"):
            self._build(tmp_path, members)

    def test_total_and_member_count_caps(self, tmp_path, monkeypatch):
        members = {"index.json": json.dumps(INDEX), "term_meta_bank_1.json": "[]"}
        monkeypatch.setattr(refs_build, "FREQ_MAX_TOTAL_BYTES", 10)
        with pytest.raises(ValueError, match="too much"):
            self._build(tmp_path, members)
        monkeypatch.setattr(refs_build, "FREQ_MAX_TOTAL_BYTES", 10**9)
        monkeypatch.setattr(refs_build, "FREQ_MAX_MEMBERS", 1)
        with pytest.raises(ValueError, match="too many"):
            self._build(tmp_path, members)

    def test_format_checks(self, tmp_path):
        with pytest.raises(ValueError, match="index.json"):
            self._build(tmp_path, {"term_meta_bank_1.json": "[]"})
        with pytest.raises(ValueError, match="unexpected frequency list format"):
            self._build(tmp_path, {"index.json": json.dumps({**INDEX, "frequencyMode": "occurrence-based"})})
        with pytest.raises(ValueError, match="no term_meta_bank"):
            self._build(tmp_path, {"index.json": json.dumps(INDEX)})

    def test_not_a_zip(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        with pytest.raises(zipfile.BadZipFile):
            refs_build.build_freq_sqlite(bad, tmp_path / "o.sqlite")


class TestEnrich:
    def test_writes_freq_rank(self, built_db, freq_db):  # noqa: F811
        _seed_vocab("市場", "しじょう")
        enrich.enrich_pending()
        item = store.list_items("vocab")[0]
        assert item["classifications"]["freq_rank"] == 900
        assert item["freq_checked"] == "rev-A"
        assert item["classifications"]["jmdict_common"] is True
        # compute_priority ignores the rank.
        assert item["priority_group"] == enrich.compute_priority(item)

    def test_previously_enriched_items_are_revisited_once(self, built_db, tmp_path):  # noqa: F811
        freq.close()
        _seed_vocab("市場", "しじょう")
        enrich.enrich_pending()
        old = store.list_items("vocab")[0]
        assert old["enriched_at"] and "freq_rank" not in old["classifications"]
        assert enrich.enrich_pending()["attempted"] == 0

        refs_build.build_freq_sqlite(make_zip(tmp_path / "f.zip"), refs_build.freq_db_path(), version="v1")
        # No flag: the next ordinary pass picks the item up...
        assert enrich.enrich_pending()["attempted"] == 1
        assert store.list_items("vocab")[0]["classifications"]["freq_rank"] == 900
        # ...and then leaves it alone.
        assert enrich.enrich_pending()["attempted"] == 0
        freq.close()

    def test_unranked_item_is_checked_once(self, built_db, freq_db):  # noqa: F811
        _seed_vocab("存在しない語", "そんざいしないご")
        assert enrich.enrich_pending()["attempted"] == 1
        item = store.list_items("vocab")[0]
        assert "freq_rank" not in item["classifications"] and item["freq_checked"] == "rev-A"
        assert enrich.enrich_pending()["attempted"] == 0

    def test_new_list_revision_triggers_reenrichment(self, built_db, freq_db, tmp_path):  # noqa: F811
        _seed_vocab("市場", "しじょう")
        enrich.enrich_pending()
        refs_build.build_freq_sqlite(
            make_zip(tmp_path / "g.zip", bank=[_kanji("市場", "しじょう", 5)], index={**INDEX, "revision": "rev-B"}),
            refs_build.freq_db_path(),
            version="v2",
        )
        assert enrich.enrich_pending()["attempted"] == 1
        assert store.list_items("vocab")[0]["classifications"]["freq_rank"] == 5

    def test_freq_alone_makes_enrichment_available(self, isolated_data_dir, freq_db):
        jmdict.close()
        _seed_vocab("嬉しい", "うれしい")
        assert enrich.enrich_pending()["available"] is True
        assert store.list_items("vocab")[0]["classifications"]["freq_rank"] == 355


class TestSortApi:
    def _items(self):
        for hw, rd, rank in [("A", "a", 50), ("B", "b", None), ("C", "c", 7), ("D", "d", None), ("E", "e", 50)]:
            store.replace_region_sightings(
                "vocab", doc_id="d1", chapter_id="c1", region_id=f"r-{hw}", source="breakdown",
                entries=[{"headword": hw, "reading": rd, "meaning": "m", "sentence_index": 0,
                          "surface": hw, "sentence_text": hw}])
            item = next(i for i in store.list_items("vocab") if i["headword"] == hw)
            if rank:
                store.update_item("vocab", item["id"], classifications={"freq_rank": rank})

    def test_frequency_sort_unranked_last_and_stable(self, isolated_data_dir):
        self._items()
        recent = [i["headword"] for i in client.get("/api/vocab").json()["items"]]
        got = [i["headword"] for i in client.get("/api/vocab?sort=frequency").json()["items"]]
        assert got[0] == "C"
        ranked, unranked = got[:3], got[3:]
        assert set(ranked) == {"C", "A", "E"} and set(unranked) == {"B", "D"}
        # Ties (A, E at 50) and the unranked tail keep newest-first order.
        assert [h for h in recent if h in {"A", "E"}] == ranked[1:]
        assert [h for h in recent if h in {"B", "D"}] == unranked

    def test_invalid_sort_still_rejected(self, isolated_data_dir):
        assert client.get("/api/vocab?sort=bogus").status_code == 400
        assert client.get("/api/grammar?sort=bogus").status_code == 400
        assert client.get("/api/grammar?sort=frequency").status_code == 400


class TestFetchAndBuild:
    def test_builds_then_reports_up_to_date_without_downloading(self, isolated_data_dir, tmp_path, monkeypatch):
        calls = []

        def fake_download(url, sha256, dest):
            calls.append((url, sha256))
            return make_zip(tmp_path / "dl.zip")

        monkeypatch.setattr(refs_build, "download_verified", fake_download)
        first = refs_build.fetch_and_build_freq()
        assert first["status"] == "built" and first["freq_rows"] == 5
        assert calls and calls[0][0].startswith("https://") and len(calls[0][1]) == 64
        assert refs_build.fetch_and_build_freq()["status"] == "up_to_date"
        assert len(calls) == 1
        freq.close()
