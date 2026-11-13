"""Populate a dev data dir with the committed sample textbook.

`make dev-backend` runs the mock VLM provider against a throwaway data dir
(`backend/.dev-data`); this module fills that dir so the UI is populated from
the first request. The content lives in `backend/seed/` (see
`backend/scripts/build_seed.py` for how the page images are made):

- chapter 1 is fully processed: transcribed regions, sentence breakdowns, a
  grammar guide, exercise completions and the vocab/grammar items harvested
  from them (with a few statuses and review events set for the dashboards);
- chapter 2 has transcribed regions only, plus one region that is drawn but
  not transcribed, so the mock pipeline can be run from the UI.

Everything goes through the same service layer the API and jobs use
(`storage`, `pdf`, `harvest`, `breakdown_links`, `srs`); no file in the storage
format is written by hand.

    python -m app.services.seed [--link-refs] [--refs-from PATH]

A no-op when the data dir already holds a document, and it refuses to touch
`backend/data` (the real study data).
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import blanks, breakdown_links, grammar_guide, harvest, pdf, srs, storage, store

log = logging.getLogger("studious.seed")

BACKEND_DIR = Path(__file__).resolve().parents[2]
SEED_DIR = BACKEND_DIR / "seed"
MANIFEST_PATH = SEED_DIR / "textbook.json"
REAL_DATA_DIR = BACKEND_DIR / "data"
SEED_MODEL = "seed"


class SeedRefusedError(Exception):
    """The configured data dir is the real study data."""


def is_real_data_dir(path: Path) -> bool:
    """True for `backend/data`: this checkout's, or any `…/backend/data` (the
    real data is only ever reached through a path like that)."""
    resolved = path.resolve()
    return resolved == REAL_DATA_DIR.resolve() or (
        resolved.name == "data" and resolved.parent.name == "backend"
    )


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text("utf-8"))


def region_text(region: dict[str, Any]) -> str:
    """A manifest region's printed text, as its transcription."""
    return "\n".join(region["lines"])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _create_document(manifest: dict[str, Any]) -> dict[str, Any]:
    """Create the document from the seed PDF the way the upload endpoint does."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / manifest["pdf"]
        shutil.copyfile(SEED_DIR / manifest["pdf"], copy)
        meta = storage.create_document(
            name=manifest["title"], source_type="pdf", page_count=0, original_path=copy
        )
    doc_dir = storage.document_dir(meta["id"])
    meta["page_count"] = pdf.render_pdf_to_pages(
        doc_dir / meta["original_filename"], doc_dir / "pages", dpi=get_settings().pdf_render_dpi
    )
    storage.save_document_meta(meta)
    return meta


def _transcribe(doc_id: str, chapter_id: str, region: dict[str, Any], manifest_region: dict[str, Any]) -> None:
    """Save a region's transcription as the region job does, harvesting a
    vocab list into the store."""
    updated = storage.update_region(
        doc_id,
        chapter_id,
        region["id"],
        transcription_md=blanks.normalize_blanks(region_text(manifest_region)),
        transcribed_at=_now_iso(),
        transcribed_model=SEED_MODEL,
    )
    if updated is not None and updated.get("tag") == "vocab_list":
        harvest.ingest_vocab_list_region(doc_id, chapter_id, updated)


def _save_breakdown(doc_id: str, chapter_id: str, region_id: str, breakdown: dict[str, Any]) -> None:
    """Save a breakdown as the breakdown job does, then harvest it."""
    sentences = json.loads(json.dumps(breakdown["sentences"]))  # private copy: annotate mutates
    for sentence in sentences:
        sentence["text"] = blanks.normalize_blanks(sentence["text"])
    payload = {"model": SEED_MODEL, "sentences": sentences}
    breakdown_links.annotate(payload)
    storage.save_breakdown(doc_id, chapter_id, region_id, payload)
    harvest.ingest_breakdown(doc_id, chapter_id, region_id, payload)


def _save_completions(doc_id: str, chapter_id: str, region_id: str, completions: dict[str, Any]) -> None:
    for index, completion in completions.items():
        entry = {
            **completion,
            "model": SEED_MODEL,
            "profile": {"level": "N4", "answer_length": "standard"},
            "updated_at": _now_iso(),
        }
        storage.upsert_exercise_completion_entry(doc_id, chapter_id, region_id, int(index), entry)


def _curate_store(curation: dict[str, Any]) -> None:
    """Set a few item statuses and add review events, so the vocab dashboard
    and the flashcard queue are not uniformly "new"."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in store.list_items("vocab"):
        by_key.setdefault(("vocab", item["headword"]), item)
    for item in store.list_items("grammar"):
        by_key.setdefault(("grammar", item["pattern"]), item)
    for kind, statuses in curation.get("statuses", {}).items():
        for name, status in statuses.items():
            item = by_key.get((kind, name))
            if item is not None:
                store.update_item(kind, item["id"], status=status)
    now = datetime.now(UTC)
    for i, (kind, name, card_type, days_ago, grade) in enumerate(curation.get("reviews", [])):
        item = by_key.get((kind, name))
        if item is None:
            continue
        srs.record_review(
            kind=kind,
            item_id=item["id"],
            card_type=card_type,
            grade=grade,
            elapsed_ms=4000,
            ts=now - timedelta(days=days_ago) + timedelta(minutes=i),
        )


def seed(data_dir: Path | None = None) -> dict[str, Any]:
    """Populate the configured data dir. Returns a summary; `seeded` is False
    (and nothing is written) when the dir already holds a document.

    Raises SeedRefusedError when the data dir is the real `backend/data`.
    """
    target = Path(data_dir) if data_dir is not None else get_settings().data_dir
    if is_real_data_dir(target):
        raise SeedRefusedError(f"refusing to seed {target.resolve()}: that is the real study data")
    if storage.list_documents():
        return {"seeded": False, "reason": "data dir already holds a document"}

    manifest = load_manifest()
    doc = _create_document(manifest)
    doc_id = doc["id"]
    key_to_ref: dict[str, dict[str, str]] = {}
    pending_refs: list[tuple[dict[str, str], list[str]]] = []
    region_count = 0
    chapters = []

    for order, ch in enumerate(manifest["chapters"]):
        chapter = storage.create_chapter(
            doc_id, title=ch["title"], page_start=ch["page_start"], page_end=ch["page_end"], order=order
        )
        chapter_id = chapter["id"]
        chapters.append(chapter)
        saved: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for mr in ch["regions"]:
            region = storage.create_region(
                doc_id, chapter_id, page=mr["page"], bbox=mr["bbox"], tag=mr["tag"], label=mr.get("label", "")
            )
            region_count += 1
            key_to_ref[mr["key"]] = {"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region["id"]}
            saved.append((region, mr))
            if mr.get("transcribed", True):
                _transcribe(doc_id, chapter_id, region, mr)
            if mr.get("references"):
                pending_refs.append((key_to_ref[mr["key"]], mr["references"]))
        for region, mr in saved:
            if mr.get("breakdown"):
                _save_breakdown(doc_id, chapter_id, region["id"], mr["breakdown"])
            if mr.get("completions"):
                _save_completions(doc_id, chapter_id, region["id"], mr["completions"])
        if ch.get("grammar_guide"):
            _, guide_regions = grammar_guide.prepare_source(doc_id, chapter_id)
            storage.save_grammar_guide(
                doc_id,
                chapter_id,
                {
                    "model": SEED_MODEL,
                    "intro": ch["grammar_guide"].get("intro", ""),
                    "points": ch["grammar_guide"]["points"],
                    "source_fingerprint": grammar_guide.fingerprint(guide_regions),
                },
            )

    for ref, target_keys in pending_refs:
        storage.update_region(
            ref["doc_id"],
            ref["chapter_id"],
            ref["region_id"],
            references=[key_to_ref[k] for k in target_keys],
        )

    _curate_store(manifest.get("store", {}))
    summary = {
        "seeded": True,
        "doc_id": doc_id,
        "chapters": len(chapters),
        "regions": region_count,
        "vocab_items": len(store.list_items("vocab")),
        "grammar_items": len(store.list_items("grammar")),
    }
    log.info("seed_done", extra=summary)
    return summary


def link_refs(data_dir: Path, source: Path) -> str:
    """Make `<data_dir>/refs` point at an existing reference-data dir.

    Returns "present" (already there), "linked" or "missing" (no source). The
    source is only checked for existence, never read; the app opens the JMdict
    index read-only.
    """
    dest = data_dir / "refs"
    if dest.exists() or dest.is_symlink():
        return "present"
    if not source.is_dir():
        return "missing"
    dest.symlink_to(source.resolve(), target_is_directory=True)
    return "linked"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--link-refs", action="store_true", help="symlink reference data into the data dir if available")
    parser.add_argument(
        "--refs-from",
        type=Path,
        default=REAL_DATA_DIR / "refs",
        help="reference data dir to link (default: backend/data/refs)",
    )
    args = parser.parse_args(argv)

    data_dir = get_settings().data_dir
    if is_real_data_dir(data_dir):
        print(f"seed: refusing to seed {data_dir}: that is the real study data", file=sys.stderr)
        return 1

    if args.link_refs:
        state = link_refs(data_dir, args.refs_from)
        if state == "linked":
            print(f"seed: linked reference data {data_dir / 'refs'} -> {args.refs_from.resolve()}")
        elif state == "missing":
            print(
                f"seed: no reference data in {data_dir / 'refs'} (JMdict/JLPT enrichment is off). "
                f"To build it here: cd backend && STUDIOUS_DATA_DIR={data_dir} uv run python scripts/fetch_refs.py"
            )

    summary = seed()
    if summary["seeded"]:
        print(
            f"seed: created the sample textbook in {data_dir} "
            f"({summary['chapters']} chapters, {summary['regions']} regions, "
            f"{summary['vocab_items']} vocab and {summary['grammar_items']} grammar items)"
        )
    else:
        print(f"seed: nothing to do, {data_dir} {summary['reason'].removeprefix('data dir ')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
