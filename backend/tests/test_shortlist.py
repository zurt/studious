from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import shortlist, store, wanikani

client = TestClient(app)


def _item(headword="勉強", **over: Any) -> dict[str, Any]:
    base = {
        "headword": headword,
        "reading": "べんきょう",
        "pos": ["n"],
        "jmdict_seq": 1,
        "status": "unreviewed",
        "classifications": {},
    }
    base.update(over)
    return base


class TestAssess:
    def test_candidate(self):
        assert shortlist.assess(_item(), None) is None

    def test_each_reason(self):
        assert shortlist.assess(_item(status="known"), None) == "status_known"
        assert shortlist.assess(_item(status="ignored"), None) == "status_ignored"
        assert shortlist.assess(_item(), {"state": "new", "match": "exact"}) == "in_anki"
        assert shortlist.assess(_item("〜ながら"), None) == "grammar_like"
        assert shortlist.assess(_item(jmdict_seq=None), None) == "not_dictionary"
        assert shortlist.assess(_item(classifications={"jlpt": "N5"}), None) == "basic"
        assert shortlist.assess(_item(classifications={"jlpt": "N4"}), None) == "basic"

    def test_n3_is_not_basic(self):
        assert shortlist.assess(_item(classifications={"jlpt": "N3"}), None) is None

    @pytest.mark.parametrize("match", ["exact", "entry"])
    @pytest.mark.parametrize("state", ["new", "learning", "young", "mature", "suspended"])
    def test_any_anki_state_excludes(self, state, match):
        assert shortlist.assess(_item(), {"state": state, "match": match}) == "in_anki"

    def test_headword_only_anki_match_does_not_exclude(self):
        assert shortlist.assess(_item(), {"state": "mature", "match": "headword"}) is None

    def test_precedence(self):
        everything = _item(
            "〜ので", status="known", jmdict_seq=None, classifications={"jlpt": "N5"}
        )
        anki = {"state": "new", "match": "exact"}
        assert shortlist.assess(everything, anki) == "status_known"
        everything["status"] = "ignored"
        assert shortlist.assess(everything, anki) == "status_ignored"
        everything["status"] = "active"
        assert shortlist.assess(everything, anki) == "in_anki"
        assert shortlist.assess(everything, None) == "grammar_like"
        assert shortlist.assess(_item(jmdict_seq=None, classifications={"jlpt": "N5"}), None) == "not_dictionary"

    @pytest.mark.parametrize("tilde", ["〜", "～", "~", "…"])
    def test_each_tilde_is_grammar_like(self, tilde):
        assert shortlist.assess(_item(f"{tilde}ている"), None) == "grammar_like"
        assert shortlist.assess(_item(f"食べ{tilde}"), None) == "grammar_like"

    @pytest.mark.parametrize("pos", ["prt", "conj", "exp", "int", "cop", "ctr", "suf", "n-suf", "pref", "n-pref", "aux-v", "aux"])
    def test_kana_only_grammar_pos(self, pos):
        assert shortlist.assess(_item("から", pos=["n", pos]), None) == "grammar_like"

    @pytest.mark.parametrize("pos", ["n", "v5r", "adv"])
    def test_kana_only_content_word_is_not_grammar_like(self, pos):
        assert shortlist.assess(_item("ふとん", pos=[pos]), None) is None

    def test_kanji_expression_is_not_grammar_like(self):
        assert shortlist.assess(_item("気をつける", pos=["exp"]), None) is None

    def test_wk_burned_does_not_exclude(self):
        assert shortlist.assess(_item(), None, True) is None


def _write_wk(tmp_path, subjects, assignments):
    d = tmp_path / "refs" / "wanikani"
    d.mkdir(parents=True, exist_ok=True)
    (d / "subjects.jsonl").write_text("".join(json.dumps(s) + "\n" for s in subjects))
    (d / "assignments.jsonl").write_text("".join(json.dumps(a) + "\n" for a in assignments))


def _subj(sid, obj, chars):
    return {"id": sid, "object": obj, "data": {"characters": chars, "level": 1}}


def _assign(aid, sid, burned_at=None, stage=9):
    return {"id": aid, "object": "assignment", "data": {
        "subject_id": sid, "srs_stage": stage, "passed_at": "2022-01-01T00:00:00Z", "burned_at": burned_at}}


class TestBurnedIndex:
    def test_burned_passed_unassigned(self, isolated_data_dir):
        _write_wk(
            isolated_data_dir,
            [_subj(1, "vocabulary", "勉強"), _subj(2, "vocabulary", "学校"),
             _subj(3, "vocabulary", "先生"), _subj(4, "kana_vocabulary", "ふとん"),
             _subj(5, "kanji", "強")],
            [_assign(10, 1, burned_at="2022-11-03T00:00:00Z"), _assign(11, 2, stage=7),
             _assign(12, 4, burned_at="2023-01-01T00:00:00Z"), _assign(13, 5, burned_at="2023-01-01T00:00:00Z")],
        )
        idx = wanikani.burned_index()
        assert idx["勉強"] is True
        assert idx["学校"] is False  # passed, not burned
        assert idx["先生"] is False  # no assignment
        assert idx["ふとん"] is True
        assert "強" not in idx  # kanji subjects are not vocabulary

    def test_never_synced_is_empty(self, isolated_data_dir):
        assert wanikani.burned_index() == {}

    def test_cached_until_files_change(self, isolated_data_dir, monkeypatch):
        _write_wk(isolated_data_dir, [_subj(1, "vocabulary", "勉強")], [_assign(10, 1)])
        calls = []
        real = wanikani._build_burned_index
        monkeypatch.setattr(wanikani, "_build_burned_index", lambda: calls.append(1) or real())
        for _ in range(5):
            assert wanikani.burned_index()["勉強"] is False
        assert len(calls) == 1
        _write_wk(isolated_data_dir, [_subj(1, "vocabulary", "勉強")],
                  [_assign(10, 1, burned_at="2022-11-03T00:00:00Z"), _assign(11, 99)])
        assert wanikani.burned_index()["勉強"] is True
        assert len(calls) == 2

    def test_not_rebuilt_per_item(self, isolated_data_dir, monkeypatch):
        _write_wk(isolated_data_dir, [_subj(1, "vocabulary", "勉強")], [_assign(10, 1)])
        for i in range(20):
            store.create_item("vocab", headword=f"語{i}", reading="ご", meaning="m")
        calls = []
        real = wanikani._build_burned_index
        monkeypatch.setattr(wanikani, "_build_burned_index", lambda: calls.append(1) or real())
        assert client.get("/api/vocab").json()["total"] == 20
        assert len(calls) == 1


def _make(headword, reading=None, *, rank=None, jlpt=None, seq=1, pos=("n",), status="unreviewed",
          sightings=()):
    item = store.create_item("vocab", headword=headword, reading=reading or headword, meaning="m")
    classes: dict[str, Any] = {}
    if rank is not None:
        classes["freq_rank"] = rank
    if jlpt:
        classes["jlpt"] = jlpt
    store.update_item(
        "vocab", item["id"], jmdict_seq=seq, pos=list(pos), status=status, classifications=classes,
        sightings=[{"doc_id": "d", "chapter_id": c, "region_id": "r", "source": s} for c, s in sightings],
    )
    return item


def _heads(url):
    return [i["headword"] for i in client.get(url).json()["items"]]


class TestApi:
    def test_fields_present_on_items(self, isolated_data_dir):
        _make("犬")
        item = client.get("/api/vocab").json()["items"][0]
        assert item["wk_burned"] is False
        assert item["shortlist_excluded"] is None
        assert "shortlist" not in client.get("/api/vocab").json()

    def test_wk_burned_joined(self, isolated_data_dir):
        _write_wk(isolated_data_dir, [_subj(1, "vocabulary", "犬")],
                  [_assign(10, 1, burned_at="2022-11-03T00:00:00Z")])
        _make("犬")
        _make("猫")
        items = {i["headword"]: i for i in client.get("/api/vocab").json()["items"]}
        assert items["犬"]["wk_burned"] is True and items["猫"]["wk_burned"] is False
        d = client.get("/api/vocab?shortlist=true").json()
        assert d["shortlist"]["wk_burned"] == 1 and d["total"] == 2

    def test_order_halving_and_unranked(self, isolated_data_dir):
        _make("a", rank=100)
        _make("b", rank=150, sightings=[("c1", "vocab_list")])  # 75
        _make("c", rank=120, sightings=[("c1", "breakdown")])  # not halved
        _make("d", "いい")  # unranked, no list
        _make("e", "あ", sightings=[("c1", "vocab_list")])  # unranked, listed -> first of unranked
        _make("f", "あ")  # unranked, reading ties with e, sorts by headword after listed
        assert _heads("/api/vocab?shortlist=true&sort=alpha") == ["b", "a", "c", "e", "f", "d"]

    def test_chapter_scoped_halving(self, isolated_data_dir):
        _make("x", rank=100, sightings=[("c2", "vocab_list"), ("c1", "breakdown")])
        _make("y", rank=80, sightings=[("c1", "vocab_list")])
        # No chapter: any vocab_list sighting halves -> x=50, y=40.
        assert _heads("/api/vocab?shortlist=true") == ["y", "x"]
        # Chapter c1 filter: x has only a breakdown sighting there -> 100; y -> 40.
        assert _heads("/api/vocab?shortlist=true&chapter_id=c1") == ["y", "x"]
        _make("z", rank=70, sightings=[("c1", "breakdown")])
        # Within c2: only x, halved; z not in c2.
        assert _heads("/api/vocab?shortlist=true&chapter_id=c2") == ["x"]
        # c1: y=40, z=70, x=100 (its vocab_list sighting is in c2, not c1).
        assert _heads("/api/vocab?shortlist=true&chapter_id=c1") == ["y", "z", "x"]

    def test_excluded_counts_and_candidates(self, isolated_data_dir):
        _make("ok", rank=1)
        _make("k", status="known")
        _make("i", status="ignored")
        _make("n5", jlpt="N5")
        _make("n4", jlpt="N4")
        _make("〜ので")
        _make("見出し", seq=None)
        d = client.get("/api/vocab?shortlist=true").json()
        assert [i["headword"] for i in d["items"]] == ["ok"]
        assert d["total"] == 1
        assert d["shortlist"]["excluded"] == {
            "status_known": 1, "status_ignored": 1, "in_anki": 0,
            "grammar_like": 1, "not_dictionary": 1, "basic": 2,
        }

    def test_excluded_counts_respect_other_filters(self, isolated_data_dir):
        _make("in", sightings=[("c1", "vocab_list")])
        _make("kn", status="known", sightings=[("c1", "vocab_list")])
        _make("other", status="known", sightings=[("c2", "vocab_list")])
        d = client.get("/api/vocab?shortlist=true&chapter_id=c1").json()
        assert d["shortlist"]["excluded"]["status_known"] == 1

    def test_in_anki_excluded(self, isolated_data_dir, monkeypatch):
        from app.services import anki

        _make("食べる")
        _make("飲む")
        monkeypatch.setattr(anki, "get_index", lambda: ({("食べる", "食べる"): {
            "state": "new", "deck": "d", "interval": 0}}, {}, {"飲む": {
                "state": "mature", "deck": "d", "interval": 9}}))
        d = client.get("/api/vocab?shortlist=true").json()
        assert [i["headword"] for i in d["items"]] == ["飲む"]  # headword-only does not exclude
        assert d["shortlist"]["excluded"]["in_anki"] == 1

    def test_paging(self, isolated_data_dir):
        for n in range(1, 6):
            _make(f"w{n}", rank=n)
        first = client.get("/api/vocab?shortlist=true&limit=2").json()
        second = client.get("/api/vocab?shortlist=true&limit=2&offset=2").json()
        assert first["total"] == second["total"] == 5
        assert [i["headword"] for i in first["items"] + second["items"]] == ["w1", "w2", "w3", "w4"]
        assert first["shortlist"] == second["shortlist"]

    def test_known_with_shortlist_is_empty(self, isolated_data_dir):
        _make("k", status="known")
        d = client.get("/api/vocab?shortlist=true&status=known").json()
        assert d["items"] == [] and d["shortlist"]["excluded"]["status_known"] == 1

    def test_excluded_filter(self, isolated_data_dir):
        _make("ok", rank=1)
        _make("b", jlpt="N5", rank=9)
        _make("a", jlpt="N4", rank=5)
        d = client.get("/api/vocab?excluded=basic&sort=frequency").json()
        assert [i["headword"] for i in d["items"]] == ["a", "b"] and d["total"] == 2
        assert all(i["shortlist_excluded"] == "basic" for i in d["items"])

    def test_invalid_and_conflicting(self, isolated_data_dir):
        assert client.get("/api/vocab?excluded=bogus").status_code == 400
        assert client.get("/api/vocab?excluded=basic&shortlist=true").status_code == 400

    def test_grammar_has_no_shortlist(self, isolated_data_dir):
        d = client.get("/api/grammar?shortlist=true&excluded=basic").json()
        assert "shortlist" not in d
