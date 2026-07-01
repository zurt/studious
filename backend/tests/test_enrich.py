from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import enrich, harvest, jmdict, refs_build, store
from tests.test_jmdict import FIXTURE_WORDS, JLPT_CSVS


@pytest.fixture
def built_db(isolated_data_dir: Path, tmp_path: Path) -> Path:
    src = tmp_path / "jmdict.json"
    src.write_text(
        json.dumps({"version": "test", "dictDate": "2026-01-01", "words": FIXTURE_WORDS}),
        encoding="utf-8",
    )
    csv_paths: dict[int, Path] = {}
    for level, content in JLPT_CSVS.items():
        p = tmp_path / f"n{level}.csv"
        p.write_text(content, encoding="utf-8")
        csv_paths[level] = p
    out = refs_build.jmdict_db_path()
    refs_build.build_sqlite(src, csv_paths, out, version="test")
    jmdict.close()
    return out


def _seed_vocab(headword: str, reading: str, meaning: str = "llm gloss"):
    store.replace_region_sightings(
        "vocab",
        doc_id="d1",
        chapter_id="c1",
        region_id="r1",
        source="breakdown",
        entries=[
            {
                "headword": headword,
                "reading": reading,
                "meaning": meaning,
                "sentence_index": 0,
                "surface": headword,
                "sentence_text": "",
            }
        ],
    )


class TestComputePriority:
    def test_buckets(self):
        def item(jlpt=None, common=False, wk=None, seq=None):
            return {
                "jmdict_seq": seq,
                "classifications": {
                    "jlpt": jlpt,
                    "jmdict_common": common,
                    "wanikani_level": wk,
                },
            }

        assert enrich.compute_priority(item(jlpt="N5")) == 1
        assert enrich.compute_priority(item(jlpt="N4")) == 1
        assert enrich.compute_priority(item(jlpt="N2")) == 2
        assert enrich.compute_priority(item(common=True, wk=12)) == 2
        assert enrich.compute_priority(item(jlpt="N1")) == 3
        assert enrich.compute_priority(item(common=True)) == 3
        assert enrich.compute_priority(item(wk=55)) == 3
        assert enrich.compute_priority(item(seq=123)) == 4
        assert enrich.compute_priority(item()) == 5


class TestEnrichPending:
    def test_links_and_classifies(self, built_db: Path):
        _seed_vocab("関わる", "かかわる")
        result = enrich.enrich_pending()
        assert result == {"available": True, "attempted": 1, "linked": 1}
        item = store.list_items("vocab")[0]
        assert item["jmdict_seq"] == 1589880
        assert item["pos"] == ["v5r", "vi"]
        assert item["meaning"].startswith("to be involved")
        assert item["meaning_source"] == "jmdict"
        assert item["classifications"]["jmdict_common"] is True
        assert item["classifications"]["jlpt"] == "N3"
        assert item["priority_group"] == 2
        assert item["links"]["jisho"].startswith("https://jisho.org/search/")
        assert item["enriched_at"]

    def test_miss_still_stamps_attempt(self, built_db: Path):
        _seed_vocab("存在しない語", "そんざいしないご")
        result = enrich.enrich_pending()
        assert result["linked"] == 0
        item = store.list_items("vocab")[0]
        assert item["jmdict_seq"] is None
        assert item["enriched_at"]
        assert item["priority_group"] == 5
        # Second pass skips it (already attempted).
        assert enrich.enrich_pending()["attempted"] == 0

    def test_force_reenriches_but_keeps_user_meaning(self, built_db: Path):
        _seed_vocab("関わる", "かかわる")
        enrich.enrich_pending()
        item = store.list_items("vocab")[0]
        store.update_item("vocab", item["id"], meaning="my nuance", meaning_source="user")
        result = enrich.enrich_pending(force=True)
        assert result["attempted"] == 1
        item = store.list_items("vocab")[0]
        assert item["meaning"] == "my nuance"
        assert item["meaning_source"] == "user"
        assert item["jmdict_seq"] == 1589880

    def test_no_index_is_noop(self, isolated_data_dir: Path):
        jmdict.close()
        _seed_vocab("関わる", "かかわる")
        assert enrich.enrich_pending() == {"available": False, "attempted": 0, "linked": 0}

    def test_jlpt_via_variant_spelling(self, built_db: Path, tmp_path: Path):
        # Fixture N2 list writes 係わる; the store item uses 関わる. The
        # JMdict entry's variant list bridges them. Rebuild the JLPT table
        # with only the variant row to isolate the path.
        import sqlite3

        con = sqlite3.connect(refs_build.jmdict_db_path())
        con.execute("DELETE FROM jlpt")
        con.execute("INSERT INTO jlpt VALUES ('係わる', 'かかわる', 2)")
        con.commit()
        con.close()
        jmdict.close()
        _seed_vocab("関わる", "かかわる")
        enrich.enrich_pending()
        item = store.list_items("vocab")[0]
        assert item["classifications"]["jlpt"] == "N2"


class TestHarvestAutoEnrich:
    def test_breakdown_ingest_enriches_new_items(self, built_db: Path):
        harvest.ingest_breakdown(
            "d1",
            "c1",
            "r1",
            {
                "sentences": [
                    {
                        "text": "様々な市場に関わる。",
                        "vocab": [{"word": "市場", "reading": "しじょう", "meaning": "market"}],
                        "grammar": [],
                    }
                ]
            },
        )
        item = store.list_items("vocab")[0]
        assert item["jmdict_seq"] == 1131
        assert item["meaning"] == "market (financial)"

    def test_backfill_reports_enriched(self, built_db: Path):
        _seed_vocab("関わる", "かかわる")
        totals = harvest.backfill()
        assert totals["enriched"] == 1
