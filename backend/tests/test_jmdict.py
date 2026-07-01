from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services import jmdict, refs_build


def _word(
    wid: str,
    kanji: list[dict] | None,
    kana: list[dict],
    senses: list[dict],
) -> dict:
    return {"id": wid, "kanji": kanji or [], "kana": kana, "sense": senses}


def _sense(pos: list[str], glosses: list[str]) -> dict:
    return {
        "partOfSpeech": pos,
        "gloss": [{"lang": "eng", "gender": None, "type": None, "text": g} for g in glosses],
    }


FIXTURE_WORDS = [
    _word(
        "1589880",
        [
            {"common": True, "text": "関わる", "tags": []},
            {"common": False, "text": "関る", "tags": ["sK"]},
        ],
        [{"common": True, "text": "かかわる", "tags": []}],
        [_sense(["v5r", "vi"], ["to be involved (in)", "to get involved (in)"])],
    ),
    # Homographs: 市場 いちば (marketplace) vs しじょう (market/exchange).
    _word(
        "1130", [{"common": True, "text": "市場", "tags": []}],
        [{"common": True, "text": "いちば", "tags": []}],
        [_sense(["n"], ["marketplace"])],
    ),
    _word(
        "1131", [{"common": True, "text": "市場", "tags": []}],
        [{"common": True, "text": "しじょう", "tags": []}],
        [_sense(["n"], ["market (financial)"])],
    ),
    _word(
        "2028980", None,
        [{"common": True, "text": "によって", "tags": []}],
        [_sense(["exp"], ["by means of", "according to"])],
    ),
    _word(
        "9001", None,
        [{"common": False, "text": "おいしい", "tags": []}],
        [_sense(["adj-i"], ["delicious"])],
    ),
    # No English gloss — must be dropped from entries entirely.
    _word("9999", None, [{"common": False, "text": "ダミー", "tags": []}], []),
]

JLPT_CSVS = {
    3: (
        "expression,reading,meaning,tags\n"
        "関わる,かかわる,to be involved,JLPT JLPT_2 JLPT_3\n"
        "さまざま,さまざま,various,JLPT JLPT_3\n"
    ),
    2: (
        "expression,reading,meaning,tags\n"
        "関わる,かかわる,to be involved,JLPT JLPT_2\n"
        "市場,いちば,market,JLPT JLPT_2\n"
    ),
    5: "expression,reading,meaning,tags\nおいしい,おいしい,delicious,JLPT JLPT_5\n",
}


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


class TestBuild:
    def test_build_stats(self, built_db: Path):
        assert built_db.exists()
        m = jmdict.meta()
        assert m["jmdict_version"] == "test"
        assert m["entries"] == "5"  # gloss-less ダミー entry dropped

    def test_checksum_mismatch_rejected(self, isolated_data_dir: Path, tmp_path: Path):
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"payload")
        url = artifact.as_uri()
        dest = tmp_path / "downloads" / "artifact.bin"
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            refs_build.download_verified(url, "0" * 64, dest)
        assert not dest.exists()
        good = hashlib.sha256(b"payload").hexdigest()
        assert refs_build.download_verified(url, good, dest) == dest
        assert dest.read_bytes() == b"payload"


class TestLookup:
    def test_lookup_by_kanji(self, built_db: Path):
        hit = jmdict.lookup("関わる", "かかわる")
        assert hit is not None
        assert hit["seq"] == 1589880
        assert hit["gloss"].startswith("to be involved")
        assert hit["pos"] == ["v5r", "vi"]
        assert hit["common"] is True
        # Search-only variant is not part of the display forms.
        assert "関る" not in hit["kanji"]

    def test_search_only_surface_still_matches(self, built_db: Path):
        hit = jmdict.lookup("関る")
        assert hit is not None
        assert hit["seq"] == 1589880

    def test_reading_disambiguates_homographs(self, built_db: Path):
        assert jmdict.lookup("市場", "いちば")["gloss"] == "marketplace"
        assert jmdict.lookup("市場", "しじょう")["gloss"] == "market (financial)"
        assert jmdict.lookup("市場", "シジョウ")["gloss"] == "market (financial)"

    def test_tilde_stripped(self, built_db: Path):
        hit = jmdict.lookup("〜によって")
        assert hit is not None
        assert hit["seq"] == 2028980

    def test_reading_fallback_when_kanji_unknown(self, built_db: Path):
        # Kanji variant not in the fixture; the reading still resolves it.
        hit = jmdict.lookup("拘わる", "かかわる")
        assert hit is not None
        assert hit["seq"] == 1589880

    def test_miss_returns_none(self, built_db: Path):
        assert jmdict.lookup("存在しない語") is None

    def test_unavailable_db(self, isolated_data_dir: Path):
        jmdict.close()
        assert jmdict.is_available() is False
        assert jmdict.lookup("関わる") is None
        assert jmdict.jlpt_level("関わる") is None


class TestJlpt:
    def test_easiest_level_wins_across_lists(self, built_db: Path):
        # 関わる appears on N2 and N3 lists; first taught at N3.
        assert jmdict.jlpt_level("関わる", "かかわる") == 3

    def test_expression_match(self, built_db: Path):
        assert jmdict.jlpt_level("市場", "いちば") == 2

    def test_kana_only_matches_reading_column(self, built_db: Path):
        assert jmdict.jlpt_level("おいしい") == 5

    def test_kanji_headword_matches_kana_listed_expression(self, built_db: Path):
        # The list writes 様々 in kana; a kanji headword still classifies
        # via its reading.
        assert jmdict.jlpt_level("様々", "さまざま") == 3

    def test_unlisted_returns_none(self, built_db: Path):
        assert jmdict.jlpt_level("によって") is None
