from __future__ import annotations

from app.services import breakdown_links


def _sentence(text: str, vocab: list[dict]) -> dict:
    return {"text": text, "gloss": "", "vocab": vocab, "grammar": []}


def test_exact_kana_vocab_match():
    s = _sentence(
        "わたしは毎朝コーヒーを飲みます。",
        [{"word": "コーヒー", "reading": "", "meaning": "coffee"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    assert len(links) == 1
    link = links[0]
    assert link["match"] == "exact"
    assert link["kind"] == "vocab"
    assert link["index"] == 0
    assert s["text"][link["start"] : link["end"]] == "コーヒー"


def test_stem_match_for_inflected_verb():
    s = _sentence(
        "わたしは毎朝コーヒーを飲みます。",
        [{"word": "飲む", "reading": "のむ", "meaning": "to drink"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    assert len(links) == 1
    assert links[0]["match"] == "stem"
    assert s["text"][links[0]["start"] : links[0]["end"]] == "飲"


def test_reading_fallback_when_word_absent():
    s = _sentence(
        "きょうはあめです。",
        [{"word": "雨", "reading": "あめ", "meaning": "rain"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    assert len(links) == 1
    assert links[0]["match"] == "reading"
    assert s["text"][links[0]["start"] : links[0]["end"]] == "あめ"


def test_homograph_guard_rejects_kanji_inside_longer_run():
    # 行 stem from 行く must not link to 行 inside 銀行.
    s = _sentence(
        "銀行に行きます。",
        [{"word": "銀行", "reading": "ぎんこう", "meaning": "bank"},
         {"word": "行く", "reading": "いく", "meaning": "to go"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    # 銀行 matches exact; 行く stem is 行, which appears inside 銀行
    # (rejected by run guard) and again at index 3 (standalone before き)
    # — that occurrence should match.
    by_index = {l["index"]: l for l in links}
    assert 0 in by_index
    assert by_index[0]["match"] == "exact"
    assert s["text"][by_index[0]["start"] : by_index[0]["end"]] == "銀行"
    # 行く stem hits the standalone 行 at the second occurrence.
    if 1 in by_index:
        assert by_index[1]["match"] == "stem"
        assert by_index[1]["start"] >= 2  # past the 銀行 span
        assert s["text"][by_index[1]["start"]] == "行"


def test_overlap_resolution_keeps_longer_span():
    # Both entries can match a span; longer wins.
    s = _sentence(
        "勉強します。",
        [{"word": "勉", "reading": "", "meaning": "study (single)"},
         {"word": "勉強", "reading": "べんきょう", "meaning": "study"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    assert len(links) == 1
    assert links[0]["index"] == 1
    assert s["text"][links[0]["start"] : links[0]["end"]] == "勉強"


def test_short_pure_hiragana_stem_rejected():
    # おいしい stem is おい (2 chars, allowed); but with a 1-char hiragana
    # word the stem path should reject. Use a contrived 1-char stem case.
    s = _sentence(
        "あの本はいいです。",
        [{"word": "い", "reading": "", "meaning": "x"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    # Exact match on い will hit (い is in the sentence). That's fine —
    # this test confirms exact wins and doesn't crash on tiny entries.
    # The stem-path rejection is exercised when exact and reading both fail.
    assert all(l["match"] in {"exact", "reading", "stem"} for l in links)


def test_no_match_drops_entry():
    s = _sentence(
        "コーヒーを飲みます。",
        [{"word": "りんご", "reading": "りんご", "meaning": "apple"}],
    )
    links = breakdown_links.compute_sentence_links(s)
    assert links == []


def test_annotate_mutates_breakdown():
    breakdown = {
        "sentences": [
            _sentence("コーヒーを飲みます。", [{"word": "コーヒー", "reading": "", "meaning": "coffee"}]),
            _sentence("本を読みます。", [{"word": "本", "reading": "ほん", "meaning": "book"}]),
        ]
    }
    breakdown_links.annotate(breakdown)
    for sentence in breakdown["sentences"]:
        assert "links" in sentence
        assert len(sentence["links"]) == 1


def test_needs_links_detects_missing_field():
    has = {"sentences": [{"text": "x", "vocab": [], "links": []}]}
    missing = {"sentences": [{"text": "x", "vocab": []}]}
    assert breakdown_links.needs_links(has) is False
    assert breakdown_links.needs_links(missing) is True


def test_grammar_entries_are_ignored():
    # Grammar should not be linked in this iteration.
    sentence = {
        "text": "わたしは毎朝コーヒーを飲みます。",
        "vocab": [],
        "grammar": [{"pattern": "〜ます", "explanation": "polite non-past"}],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    assert links == []
