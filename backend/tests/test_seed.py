"""The committed sample textbook and the seeder that loads it into a dev data dir."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import (
    BREAKDOWN_TOOL_SCHEMA,
    EXERCISE_COMPLETION_TOOL_SCHEMA,
    GRAMMAR_GUIDE_TOOL_SCHEMA,
)
from app.services import harvest, seed, srs, storage, store

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


class _Invalid(AssertionError):
    pass


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Check `value` against the subset of JSON Schema the tool schemas use
    (type, required, properties, items, minItems, maxItems, minLength, enum);
    jsonschema is not a project dependency."""
    if "type" in schema and not isinstance(value, _TYPES[schema["type"]]):
        raise _Invalid(f"{path}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise _Invalid(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise _Invalid(f"{path}: shorter than minLength")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise _Invalid(f"{path}: missing {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise _Invalid(f"{path}: item count {len(value)} out of range")
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")


def test_validator_catches_violations():
    with pytest.raises(_Invalid):
        validate({"sentences": []}, BREAKDOWN_TOOL_SCHEMA)
    with pytest.raises(_Invalid):
        validate({"sentences": [{"text": "x"}]}, BREAKDOWN_TOOL_SCHEMA)
    with pytest.raises(_Invalid):
        validate({"exercise_type": "nope"}, EXERCISE_COMPLETION_TOOL_SCHEMA)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return seed.load_manifest()


def _regions(manifest: dict):
    for ch in manifest["chapters"]:
        for region in ch["regions"]:
            yield ch, region


# ---------- the manifest itself ----------


def test_manifest_bboxes_lie_within_pages(manifest):
    for ch, region in _regions(manifest):
        x1, y1, x2, y2 = region["bbox"]
        assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1, region["key"]
        assert ch["page_start"] <= region["page"] <= ch["page_end"], region["key"]


def test_manifest_regions_on_a_page_do_not_overlap(manifest):
    by_page: dict[int, list[tuple[str, list[float]]]] = {}
    for _, region in _regions(manifest):
        by_page.setdefault(region["page"], []).append((region["key"], region["bbox"]))
    for boxes in by_page.values():
        for i, (ka, a) in enumerate(boxes):
            for kb, b in boxes[i + 1 :]:
                separate = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
                assert separate, f"{ka} overlaps {kb}"


def test_manifest_tags_are_valid_and_pdf_has_the_pages(manifest):
    import fitz

    valid = {"vocab_list", "grammar_points", "reading_passage", "exercises", "instructions", "other"}
    assert {r["tag"] for _, r in _regions(manifest)} <= valid
    with fitz.open(seed.SEED_DIR / manifest["pdf"]) as doc:
        assert doc.page_count == max(r["page"] for _, r in _regions(manifest))
        # Image-only: nothing in the PDF needs a font at seed time.
        assert all(not page.get_fonts() for page in doc)


def test_chapter_one_artifacts_match_the_tool_schemas(manifest):
    ch1 = manifest["chapters"][0]
    validate(ch1["grammar_guide"], GRAMMAR_GUIDE_TOOL_SCHEMA)
    with_breakdown = [r for r in ch1["regions"] if r.get("breakdown")]
    assert with_breakdown
    for region in with_breakdown:
        validate(region["breakdown"], BREAKDOWN_TOOL_SCHEMA)
        for completion in region.get("completions", {}).values():
            validate(completion, EXERCISE_COMPLETION_TOOL_SCHEMA)


def test_grammar_surfaces_are_substrings_of_their_sentence(manifest):
    for _, region in _regions(manifest):
        for sentence in (region.get("breakdown") or {}).get("sentences", []):
            for grammar in sentence.get("grammar", []):
                for surface in grammar["surfaces"]:
                    assert surface in sentence["text"], (region["key"], surface, sentence["text"])


def test_breakdown_sentences_are_copied_from_the_region_text(manifest):
    for _, region in _regions(manifest):
        text = seed.region_text(region)
        for sentence in (region.get("breakdown") or {}).get("sentences", []):
            assert sentence["text"] in text, (region["key"], sentence["text"])


def test_filled_text_is_a_substring_of_the_answer(manifest):
    seen_types = set()
    for _, region in _regions(manifest):
        n_sentences = len((region.get("breakdown") or {}).get("sentences", []))
        for index, completion in region.get("completions", {}).items():
            assert int(index) < n_sentences
            seen_types.add(completion["exercise_type"])
            if completion["filled_text"]:
                assert completion["filled_text"] in completion["answer"]
            if completion["exercise_type"] != "open":
                assert completion["examples"] == []
    assert seen_types == {"open", "constrained", "question"}


def test_vocab_list_lines_follow_the_prompt_format(manifest):
    for _, region in _regions(manifest):
        if region["tag"] != "vocab_list":
            continue
        parsed = harvest.parse_vocab_list_markdown(seed.region_text(region))
        assert len(parsed) == len(region["lines"]), region["key"]  # every line is an entry
        assert all(line.endswith("  ") or "　" in line for line in region["lines"])


def test_blanks_use_five_fullwidth_underscores(manifest):
    for _, region in _regions(manifest):
        for line in region["lines"]:
            assert "_" not in line.replace("＿", "")
            for run in line.split("＿＿＿＿＿"):
                assert "＿" not in run, line


# ---------- the seeder ----------


def test_seed_populates_a_fresh_data_dir(isolated_data_dir: Path, manifest):
    summary = seed.seed()
    assert summary["seeded"] is True

    docs = storage.list_documents()
    assert len(docs) == 1
    doc = docs[0]
    assert doc["name"] == manifest["title"]
    assert doc["page_count"] == 5
    for page in range(1, doc["page_count"] + 1):
        assert storage.page_image_path(doc["id"], page).exists()

    chapters = storage.list_chapters(doc["id"])
    assert [c["title"] for c in chapters] == [c["title"] for c in manifest["chapters"]]
    ch1, ch2 = chapters

    regions1 = storage.list_regions(doc["id"], ch1["id"])
    regions2 = storage.list_regions(doc["id"], ch2["id"])
    assert len(regions1) == 5 and len(regions2) == 5
    assert all(r["transcription_md"] for r in regions1)
    untranscribed = [r for r in regions2 if not r["transcription_md"]]
    assert [r["label"] for r in untranscribed] == ["練習B"]
    assert all(r["transcribed_model"] == "seed" for r in regions1)


def test_seed_chapter_one_is_fully_processed(isolated_data_dir: Path, manifest):
    seed.seed()
    doc = storage.list_documents()[0]
    ch1, ch2 = storage.list_chapters(doc["id"])
    by_label = {r["label"]: r for r in storage.list_regions(doc["id"], ch1["id"])}

    reading = by_label["本文「私の一日」"]
    breakdown = storage.load_breakdown(doc["id"], ch1["id"], reading["id"])
    assert len(breakdown["sentences"]) == 9
    assert all("links" in s for s in breakdown["sentences"])
    validate({"sentences": breakdown["sentences"]}, BREAKDOWN_TOOL_SCHEMA)

    exercises = by_label["練習A・B・C"]
    assert exercises["references"] == [
        {"doc_id": doc["id"], "chapter_id": ch1["id"], "region_id": reading["id"]}
    ]
    record = storage.load_exercise_completion(doc["id"], ch1["id"], exercises["id"])
    assert {c["exercise_type"] for c in record["completions"].values()} == {"open", "constrained", "question"}

    guide = storage.load_grammar_guide(doc["id"], ch1["id"])
    validate({"intro": guide["intro"], "points": guide["points"]}, GRAMMAR_GUIDE_TOOL_SCHEMA)

    # Chapter 2 is left for the mock pipeline to process.
    for region in storage.list_regions(doc["id"], ch2["id"]):
        assert storage.load_breakdown(doc["id"], ch2["id"], region["id"]) is None
        assert storage.load_exercise_completion(doc["id"], ch2["id"], region["id"]) is None
    assert storage.load_grammar_guide(doc["id"], ch2["id"]) is None


def test_seed_harvests_store_items_with_varied_status_and_reviews(isolated_data_dir: Path):
    seed.seed()
    vocab = store.list_items("vocab")
    grammar = store.list_items("grammar")
    assert vocab and grammar
    assert {i["status"] for i in vocab} >= {"unreviewed", "active", "known", "ignored"}
    assert {i["status"] for i in grammar} >= {"unreviewed", "active", "known"}

    by_head = {i["headword"]: i for i in vocab}
    assert srs.card_state("vocab", by_head["起きる"]["id"], "word").seen
    assert not srs.card_state("vocab", by_head["顔"]["id"], "word").seen


def test_seed_is_a_noop_when_the_dir_already_has_a_document(isolated_data_dir: Path):
    seed.seed()
    before = sorted(p.relative_to(isolated_data_dir) for p in isolated_data_dir.rglob("*"))
    summary = seed.seed()
    assert summary["seeded"] is False
    assert len(storage.list_documents()) == 1
    assert sorted(p.relative_to(isolated_data_dir) for p in isolated_data_dir.rglob("*")) == before


def test_seed_cli_reports_a_noop_and_exits_zero(isolated_data_dir: Path, capsys):
    assert seed.main([]) == 0
    assert "created the sample textbook" in capsys.readouterr().out
    assert seed.main([]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_seed_refuses_the_real_data_dir():
    real = seed.REAL_DATA_DIR
    assert real.name == "data" and real.parent.name == "backend"
    with pytest.raises(seed.SeedRefusedError):
        seed.seed(real)
    # Also any other path that looks like <something>/backend/data.
    with pytest.raises(seed.SeedRefusedError):
        seed.seed(Path("/somewhere/else/backend/data"))


def test_seed_cli_refuses_the_real_data_dir(monkeypatch, capsys):
    # A stand-in for the settings: the real get_settings() would create
    # directories under the path it is given.
    monkeypatch.setattr(seed, "get_settings", lambda: SimpleNamespace(data_dir=seed.REAL_DATA_DIR))
    assert seed.main([]) == 1
    assert "real study data" in capsys.readouterr().err


def test_is_real_data_dir_distinguishes_dev_dirs():
    assert seed.is_real_data_dir(seed.BACKEND_DIR / "data")
    assert seed.is_real_data_dir(seed.BACKEND_DIR / "data" / ".." / "data")
    assert not seed.is_real_data_dir(seed.BACKEND_DIR / ".dev-data")
    assert not seed.is_real_data_dir(seed.BACKEND_DIR / ".e2e-data")


# ---------- reference data link ----------


def test_link_refs_symlinks_an_existing_dir_without_reading_it(tmp_path: Path):
    source = tmp_path / "real" / "refs"
    source.mkdir(parents=True)
    (source / "marker").write_text("x")
    data = tmp_path / "dev"
    data.mkdir()

    assert seed.link_refs(data, source) == "linked"
    assert (data / "refs").is_symlink()
    assert (data / "refs" / "marker").read_text() == "x"
    assert seed.link_refs(data, source) == "present"


def test_link_refs_reports_missing_source(tmp_path: Path):
    data = tmp_path / "dev"
    data.mkdir()
    assert seed.link_refs(data, tmp_path / "nope") == "missing"
    assert not (data / "refs").exists()


# ---------- env precedence for the dev target ----------


def test_dotenv_does_not_override_variables_already_in_the_environment(tmp_path: Path, monkeypatch):
    """`make dev-backend` sets STUDIOUS_DATA_DIR and empties the API keys on
    the command line; backend/.env must not be able to undo that."""
    import inspect

    from dotenv import load_dotenv

    from app import config

    # config calls load_dotenv() with the default override=False...
    assert "load_dotenv()" in inspect.getsource(config)
    assert "override=True" not in inspect.getsource(config)

    # ...which leaves variables already set, including empty ones, alone.
    env_file = tmp_path / ".env"
    env_file.write_text("STUDIOUS_DATA_DIR=./data\nANTHROPIC_API_KEY=sk-from-dotenv\nWANIKANI_API_TOKEN=wk\n")
    monkeypatch.setenv("STUDIOUS_DATA_DIR", ".dev-data")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("WANIKANI_API_TOKEN", raising=False)
    load_dotenv(env_file)
    import os

    assert os.environ["STUDIOUS_DATA_DIR"] == ".dev-data"
    assert os.environ["ANTHROPIC_API_KEY"] == ""
    assert os.environ["WANIKANI_API_TOKEN"] == "wk"  # unset variables do come from .env
