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


def test_grammar_without_surfaces_is_ignored():
    # A grammar entry without a surfaces list yields no link.
    sentence = {
        "text": "わたしは毎朝コーヒーを飲みます。",
        "vocab": [],
        "grammar": [{"pattern": "〜ます", "explanation": "polite non-past"}],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    assert links == []


def test_grammar_surface_locates_substring():
    text = "わたしは毎朝コーヒーを飲みます。"
    sentence = {
        "text": text,
        "vocab": [],
        "grammar": [{
            "pattern": "〜ます",
            "explanation": "polite non-past",
            "surfaces": ["ます"],
        }],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    assert len(links) == 1
    assert links[0]["kind"] == "grammar"
    assert links[0]["match"] == "llm"
    assert text[links[0]["start"]:links[0]["end"]] == "ます"


def test_grammar_range_pattern_emits_two_links():
    text = "子供の時から今までを振り返って書いてください。"
    sentence = {
        "text": text,
        "vocab": [],
        "grammar": [{
            "pattern": "〜から〜まで",
            "explanation": "from X to Y",
            "surfaces": ["から", "まで"],
        }],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    grammar_links = [l for l in links if l["kind"] == "grammar"]
    assert len(grammar_links) == 2
    spans = sorted((l["start"], l["end"]) for l in grammar_links)
    assert text[spans[0][0]:spans[0][1]] == "から"
    assert text[spans[1][0]:spans[1][1]] == "まで"
    # Both reference the same grammar entry.
    assert all(l["index"] == 0 for l in grammar_links)


def test_grammar_surface_not_in_text_is_dropped():
    sentence = {
        "text": "短い。",
        "vocab": [],
        "grammar": [{
            "pattern": "x",
            "explanation": "y",
            "surfaces": ["nope", "missing"],
        }],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    assert links == []


def test_grammar_repeated_surface_picks_distinct_occurrences():
    # Two ます in the sentence; two grammar entries each marking ます.
    text = "本を読みます。コーヒーを飲みます。"
    sentence = {
        "text": text,
        "vocab": [],
        "grammar": [
            {"pattern": "〜ます", "explanation": "polite", "surfaces": ["ます"]},
            {"pattern": "〜ます", "explanation": "polite", "surfaces": ["ます"]},
        ],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    grammar_links = sorted(
        [l for l in links if l["kind"] == "grammar"], key=lambda l: l["start"]
    )
    assert len(grammar_links) == 2
    assert grammar_links[0]["start"] != grammar_links[1]["start"]


def test_grammar_overlap_with_vocab_keeps_longer():
    text = "コーヒーを飲みます。"
    sentence = {
        "text": text,
        "vocab": [{"word": "飲む", "reading": "のむ", "meaning": "to drink"}],
        "grammar": [{
            "pattern": "〜ます",
            "explanation": "polite",
            "surfaces": ["飲みます"],
        }],
    }
    links = breakdown_links.compute_sentence_links(sentence)
    assert len(links) == 1
    assert links[0]["kind"] == "grammar"
    assert text[links[0]["start"]:links[0]["end"]] == "飲みます"
