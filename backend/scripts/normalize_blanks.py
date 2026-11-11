"""Rewrite stored fill-in blanks to the canonical `＿＿＿＿＿` form.

Usage (from backend/):
    uv run python scripts/normalize_blanks.py            # dry run, report only
    uv run python scripts/normalize_blanks.py --apply    # write changes

Covers page transcriptions, region transcriptions, and breakdown sentence
text (breakdown links are recomputed because sentence offsets shift).
Idempotent; only underscore-family runs are touched. Stop the dev server
first so it does not race the writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ for `app` imports

from app.services import breakdown_links, storage  # noqa: E402
from app.services.blanks import normalize_blanks  # noqa: E402


def _dump(path: Path, payload: dict) -> None:
    storage._atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()

    counts = {"transcriptions": 0, "regions": 0, "breakdowns": 0}

    for doc in storage.list_documents():
        doc_id = doc["id"]

        tdir = storage.transcription_path(doc_id, 1).parent
        for path in sorted(tdir.glob("*.json")) if tdir.exists() else []:
            payload = json.loads(path.read_text(encoding="utf-8"))
            md = payload.get("markdown")
            if isinstance(md, str) and normalize_blanks(md) != md:
                counts["transcriptions"] += 1
                if args.apply:
                    payload["markdown"] = normalize_blanks(md)
                    _dump(path, payload)

        for chapter in storage.list_chapters(doc_id):
            chapter_id = chapter["id"]
            for region in storage.list_regions(doc_id, chapter_id):
                region_id = region["id"]
                md = region.get("transcription_md")
                if isinstance(md, str) and normalize_blanks(md) != md:
                    counts["regions"] += 1
                    if args.apply:
                        storage.update_region(
                            doc_id, chapter_id, region_id, transcription_md=normalize_blanks(md)
                        )

                record = storage.load_breakdown(doc_id, chapter_id, region_id)
                if not record:
                    continue
                changed = False
                for sentence in record.get("sentences") or []:
                    text = sentence.get("text") if isinstance(sentence, dict) else None
                    if isinstance(text, str) and normalize_blanks(text) != text:
                        sentence["text"] = normalize_blanks(text)
                        changed = True
                if changed:
                    counts["breakdowns"] += 1
                    if args.apply:
                        breakdown_links.annotate(record)
                        _dump(storage.breakdown_path(doc_id, chapter_id, region_id), record)

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"{verb}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
