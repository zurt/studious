from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import store


def _sighting_entry(**over):
    entry = {
        "headword": "口べた",
        "reading": "くちべた",
        "meaning": "poor speaker",
        "sentence_index": 0,
        "surface": "口べた",
        "sentence_text": "口べたで料理好きの父親。",
    }
    entry.update(over)
    return entry


def _ingest(entries, *, region_id="r1", source="breakdown", kind="vocab"):
    return store.replace_region_sightings(
        kind,
        doc_id="d1",
        chapter_id="c1",
        region_id=region_id,
        source=source,
        entries=entries,
    )


class TestNormalization:
    def test_katakana_reading_normalizes_to_hiragana(self):
        assert store.vocab_key("関わる", "カカワル") == ("関わる", "かかわる")

    def test_kana_only_headword_gets_own_reading(self):
        assert store.vocab_key("おいしい", None) == ("おいしい", "おいしい")
        assert store.vocab_key("おいしい", "おいしい") == ("おいしい", "おいしい")

    def test_kanji_headword_without_reading_has_empty_reading(self):
        assert store.vocab_key("関わる", None) == ("関わる", "")

    def test_nfkc_normalizes_width(self):
        # Full-width alphanumerics and half-width katakana fold together.
        assert store.vocab_key("ＯＬ", "オーエル") == ("OL", "おーえる")

    def test_pattern_strips_tildes_and_spaces(self):
        assert store.normalize_pattern("〜に関わらず") == "に関わらず"
        assert store.normalize_pattern("～て もらう") == "てもらう"
        assert store.normalize_pattern("…ようになる") == "ようになる"


class TestCrud:
    def test_create_and_get(self, isolated_data_dir: Path):
        item = store.create_item(
            "vocab", headword="関わる", reading="かかわる", meaning="to be involved"
        )
        assert item["status"] == "unreviewed"
        assert store.get_item("vocab", item["id"]) == item
        assert [i["id"] for i in store.list_items("vocab")] == [item["id"]]

    def test_update_appends_latest_wins(self, isolated_data_dir: Path):
        item = store.create_item(
            "vocab", headword="関わる", reading="かかわる", meaning="to be involved"
        )
        updated = store.update_item("vocab", item["id"], status="active", notes="n")
        assert updated is not None
        assert updated["status"] == "active"
        assert updated["updated_at"] >= item["updated_at"]
        lines = store.store_path("vocab").read_text("utf-8").strip().splitlines()
        assert len(lines) == 2
        assert store.get_item("vocab", item["id"])["status"] == "active"

    def test_update_missing_returns_none(self, isolated_data_dir: Path):
        assert store.update_item("vocab", "nope", status="active") is None

    def test_delete_tombstones(self, isolated_data_dir: Path):
        item = store.create_item(
            "vocab", headword="関わる", reading="かかわる", meaning="x"
        )
        assert store.delete_item("vocab", item["id"]) is True
        assert store.list_items("vocab") == []
        assert store.get_item("vocab", item["id"])["deleted"] is True
        # Deletes are final: no re-delete, no update.
        assert store.delete_item("vocab", item["id"]) is False
        assert store.update_item("vocab", item["id"], status="active") is None

    def test_grammar_pattern_update_renormalizes(self, isolated_data_dir: Path):
        item = store.create_item("grammar", pattern="〜てもらう", explanation="e")
        assert item["pattern_normalized"] == "てもらう"
        updated = store.update_item("grammar", item["id"], pattern="〜てあげる")
        assert updated["pattern_normalized"] == "てあげる"

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            store.store_path("nope")

    def test_malformed_line_skipped(self, isolated_data_dir: Path):
        item = store.create_item("vocab", headword="犬", reading="いぬ", meaning="dog")
        with open(store.store_path("vocab"), "a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        assert [i["id"] for i in store.list_items("vocab")] == [item["id"]]

    def test_stats_counts_by_status(self, isolated_data_dir: Path):
        a = store.create_item("vocab", headword="a", reading="あ", meaning="1")
        store.create_item("vocab", headword="b", reading="び", meaning="2")
        store.update_item("vocab", a["id"], status="known")
        s = store.stats("vocab")
        assert s["total"] == 2
        assert s["unreviewed"] == 1
        assert s["known"] == 1


class TestReplaceRegionSightings:
    def test_creates_unreviewed_items_with_sightings(self, isolated_data_dir: Path):
        result = _ingest([_sighting_entry()])
        assert result == {"created": 1, "updated": 0, "sightings": 1}
        items = store.list_items("vocab")
        assert len(items) == 1
        item = items[0]
        assert item["status"] == "unreviewed"
        assert item["reading"] == "くちべた"
        assert len(item["sightings"]) == 1
        s = item["sightings"][0]
        assert s["region_id"] == "r1"
        assert s["source"] == "breakdown"
        assert s["sentence_text"].startswith("口べた")

    def test_reingest_is_idempotent(self, isolated_data_dir: Path):
        _ingest([_sighting_entry()])
        result = _ingest([_sighting_entry()])
        assert result["created"] == 0
        items = store.list_items("vocab")
        assert len(items) == 1
        assert len(items[0]["sightings"]) == 1

    def test_removed_entry_drops_sighting(self, isolated_data_dir: Path):
        _ingest([_sighting_entry(), _sighting_entry(headword="犬", reading="いぬ", meaning="dog")])
        _ingest([_sighting_entry()])  # 犬 vanished on regenerate
        by_hw = {i["headword"]: i for i in store.list_items("vocab")}
        assert len(by_hw["口べた"]["sightings"]) == 1
        assert by_hw["犬"]["sightings"] == []

    def test_same_word_from_other_region_merges(self, isolated_data_dir: Path):
        _ingest([_sighting_entry()], region_id="r1")
        item = store.list_items("vocab")[0]
        store.update_item("vocab", item["id"], status="active", meaning="curated")
        result = _ingest(
            [_sighting_entry(reading="クチベタ", meaning="clumsy speaker")],
            region_id="r2",
        )
        assert result == {"created": 0, "updated": 1, "sightings": 1}
        items = store.list_items("vocab")
        assert len(items) == 1
        merged = items[0]
        # Curated fields survive; the new sighting is added.
        assert merged["status"] == "active"
        assert merged["meaning"] == "curated"
        assert {s["region_id"] for s in merged["sightings"]} == {"r1", "r2"}

    def test_vocab_list_and_breakdown_sources_coexist(self, isolated_data_dir: Path):
        _ingest([_sighting_entry()], region_id="r1", source="breakdown")
        _ingest(
            [_sighting_entry(sentence_index=None, sentence_text="")],
            region_id="r9",
            source="vocab_list",
        )
        # Re-running the vocab_list ingest must not disturb breakdown sightings.
        _ingest(
            [_sighting_entry(sentence_index=None, sentence_text="")],
            region_id="r9",
            source="vocab_list",
        )
        items = store.list_items("vocab")
        assert len(items) == 1
        sources = sorted(s["source"] for s in items[0]["sightings"])
        assert sources == ["breakdown", "vocab_list"]

    def test_duplicate_entries_in_one_run_create_one_item(self, isolated_data_dir: Path):
        result = _ingest([_sighting_entry(sentence_index=0), _sighting_entry(sentence_index=3)])
        assert result["created"] == 1
        items = store.list_items("vocab")
        assert len(items) == 1
        assert len(items[0]["sightings"]) == 2

    def test_tombstoned_item_not_resurrected(self, isolated_data_dir: Path):
        _ingest([_sighting_entry()])
        item = store.list_items("vocab")[0]
        store.delete_item("vocab", item["id"])
        result = _ingest([_sighting_entry()], region_id="r2")
        assert result["created"] == 0
        assert store.list_items("vocab") == []

    def test_blank_headword_skipped(self, isolated_data_dir: Path):
        result = _ingest([_sighting_entry(headword="  ")])
        assert result["created"] == 0
        assert store.list_items("vocab") == []

    def test_grammar_entries(self, isolated_data_dir: Path):
        result = store.replace_region_sightings(
            "grammar",
            doc_id="d1",
            chapter_id="c1",
            region_id="r1",
            source="breakdown",
            entries=[
                {
                    "pattern": "〜に関わらず",
                    "explanation": "regardless of",
                    "sentence_index": 1,
                    "surface": "天候に関わらず",
                    "sentence_text": "天候に関わらず行われる。",
                }
            ],
        )
        assert result["created"] == 1
        item = store.list_items("grammar")[0]
        assert item["pattern_normalized"] == "に関わらず"
        # A tilde-less variant of the same pattern merges.
        store.replace_region_sightings(
            "grammar",
            doc_id="d1",
            chapter_id="c1",
            region_id="r2",
            source="breakdown",
            entries=[{"pattern": "に関わらず", "explanation": "x", "sentence_index": 0}],
        )
        items = store.list_items("grammar")
        assert len(items) == 1
        assert len(items[0]["sightings"]) == 2

    def test_unknown_source_raises(self, isolated_data_dir: Path):
        with pytest.raises(ValueError):
            _ingest([_sighting_entry()], source="scraped")

    def test_store_file_is_jsonl(self, isolated_data_dir: Path):
        _ingest([_sighting_entry()])
        raw = store.store_path("vocab").read_text("utf-8")
        for line in raw.strip().splitlines():
            json.loads(line)


class TestMerge:
    def _two_dupes(self):
        _ingest([_sighting_entry()])
        _ingest(
            [_sighting_entry(headword="口下手", surface="口下手")],
            region_id="r2",
        )
        items = {i["headword"]: i for i in store.list_items("vocab")}
        return items["口べた"], items["口下手"]

    def test_merge_unions_sightings_and_tombstones_source(self, isolated_data_dir: Path):
        target, source = self._two_dupes()
        merged = store.merge_items("vocab", target["id"], source["id"])
        assert merged is not None
        assert len(merged["sightings"]) == 2
        assert "口下手" in merged["surface_variants"]
        live = store.list_items("vocab")
        assert [i["id"] for i in live] == [target["id"]]
        tomb = store.get_item("vocab", source["id"])
        assert tomb["deleted"] is True
        assert tomb["merged_into"] == target["id"]

    def test_merge_keeps_target_curation_and_adopts_when_unreviewed(
        self, isolated_data_dir: Path
    ):
        target, source = self._two_dupes()
        store.update_item("vocab", source["id"], status="known", notes="dup note")
        merged = store.merge_items("vocab", target["id"], source["id"])
        # Target was unreviewed → adopts the source's curated status.
        assert merged["status"] == "known"
        assert "dup note" in merged["notes"]

    def test_merge_does_not_downgrade_target_status(self, isolated_data_dir: Path):
        target, source = self._two_dupes()
        store.update_item("vocab", target["id"], status="active")
        merged = store.merge_items("vocab", target["id"], source["id"])
        assert merged["status"] == "active"

    def test_merge_missing_or_deleted_returns_none(self, isolated_data_dir: Path):
        target, source = self._two_dupes()
        assert store.merge_items("vocab", target["id"], "nope") is None
        store.delete_item("vocab", source["id"])
        assert store.merge_items("vocab", target["id"], source["id"]) is None

    def test_merge_self_raises(self, isolated_data_dir: Path):
        target, _ = self._two_dupes()
        with pytest.raises(ValueError):
            store.merge_items("vocab", target["id"], target["id"])

    def test_reharvest_of_merged_variant_lands_on_canonical(
        self, isolated_data_dir: Path
    ):
        target, source = self._two_dupes()
        store.merge_items("vocab", target["id"], source["id"])
        # New sighting of the merged-away spelling redirects to the canonical.
        _ingest(
            [_sighting_entry(headword="口下手", surface="口下手", sentence_index=5)],
            region_id="r3",
        )
        items = store.list_items("vocab")
        assert len(items) == 1
        assert items[0]["id"] == target["id"]
        assert any(s["region_id"] == "r3" for s in items[0]["sightings"])

    def test_merge_fills_empty_fields_from_source(self, isolated_data_dir: Path):
        _ingest([_sighting_entry(meaning="")])
        _ingest(
            [_sighting_entry(headword="口下手", surface="口下手")],
            region_id="r2",
        )
        items = {i["headword"]: i for i in store.list_items("vocab")}
        merged = store.merge_items(
            "vocab", items["口べた"]["id"], items["口下手"]["id"]
        )
        assert merged["meaning"] == "poor speaker"

    def test_grammar_merge(self, isolated_data_dir: Path):
        for pattern, region in (("〜に関わらず", "r1"), ("〜にかかわらず", "r2")):
            store.replace_region_sightings(
                "grammar",
                doc_id="d1",
                chapter_id="c1",
                region_id=region,
                source="breakdown",
                entries=[{"pattern": pattern, "explanation": "regardless", "sentence_index": 0}],
            )
        items = store.list_items("grammar")
        assert len(items) == 2
        merged = store.merge_items("grammar", items[1]["id"], items[0]["id"])
        assert len(merged["sightings"]) == 2
        assert len(store.list_items("grammar")) == 1
