from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import get_settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _docs_root() -> Path:
    return get_settings().data_dir / "documents"


def _jobs_root() -> Path:
    return get_settings().data_dir / "jobs"


# ---------- Documents ----------


def create_document(
    *,
    name: str,
    source_type: str,
    page_count: int,
    original_path: Path,
) -> dict[str, Any]:
    doc_id = uuid.uuid4().hex[:12]
    doc_dir = _docs_root() / doc_id
    (doc_dir / "pages").mkdir(parents=True, exist_ok=True)
    (doc_dir / "transcriptions").mkdir(parents=True, exist_ok=True)

    suffix = original_path.suffix.lower() or ""
    dest = doc_dir / f"original{suffix}"
    shutil.move(str(original_path), dest)

    meta = {
        "id": doc_id,
        "name": name,
        "source_type": source_type,
        "page_count": page_count,
        "created_at": _now_iso(),
        "original_filename": f"original{suffix}",
    }
    _atomic_write_text(doc_dir / "meta.json", json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


def list_documents() -> list[dict[str, Any]]:
    root = _docs_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        meta_path = child / "meta.json"
        if meta_path.exists():
            out.append(json.loads(meta_path.read_text("utf-8")))
    out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return out


def load_document(doc_id: str) -> dict[str, Any] | None:
    meta_path = _docs_root() / doc_id / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text("utf-8"))


def document_dir(doc_id: str) -> Path:
    return _docs_root() / doc_id


def page_image_path(doc_id: str, page: int) -> Path:
    return document_dir(doc_id) / "pages" / f"{page:04d}.png"


def transcription_path(doc_id: str, page: int) -> Path:
    return document_dir(doc_id) / "transcriptions" / f"{page:04d}.json"


def save_transcription(doc_id: str, page: int, payload: dict[str, Any]) -> None:
    _atomic_write_text(
        transcription_path(doc_id, page),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def load_transcription(doc_id: str, page: int) -> dict[str, Any] | None:
    p = transcription_path(doc_id, page)
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


def transcribed_pages(doc_id: str) -> list[int]:
    d = document_dir(doc_id) / "transcriptions"
    if not d.exists():
        return []
    pages: list[int] = []
    for f in d.iterdir():
        if f.suffix == ".json" and f.stem.isdigit():
            pages.append(int(f.stem))
    return sorted(pages)


# ---------- Chapters ----------


def _chapters_dir(doc_id: str) -> Path:
    return document_dir(doc_id) / "chapters"


def create_chapter(
    doc_id: str,
    *,
    title: str,
    page_start: int,
    page_end: int,
    order: int = 0,
) -> dict[str, Any]:
    chapter_id = uuid.uuid4().hex[:12]
    chapter_dir = _chapters_dir(doc_id) / chapter_id
    (chapter_dir / "regions").mkdir(parents=True, exist_ok=True)
    meta = {
        "id": chapter_id,
        "doc_id": doc_id,
        "title": title,
        "page_start": page_start,
        "page_end": page_end,
        "order": order,
        "created_at": _now_iso(),
    }
    _atomic_write_text(chapter_dir / "meta.json", json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


def list_chapters(doc_id: str) -> list[dict[str, Any]]:
    root = _chapters_dir(doc_id)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        meta_path = child / "meta.json"
        if meta_path.exists():
            out.append(json.loads(meta_path.read_text("utf-8")))
    out.sort(key=lambda m: m.get("order", 0))
    return out


def load_chapter(doc_id: str, chapter_id: str) -> dict[str, Any] | None:
    meta_path = _chapters_dir(doc_id) / chapter_id / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text("utf-8"))


def update_chapter(doc_id: str, chapter_id: str, **changes: Any) -> dict[str, Any] | None:
    chapter = load_chapter(doc_id, chapter_id)
    if chapter is None:
        return None
    chapter.update(changes)
    _atomic_write_text(
        _chapters_dir(doc_id) / chapter_id / "meta.json",
        json.dumps(chapter, indent=2, ensure_ascii=False),
    )
    return chapter


def delete_chapter(doc_id: str, chapter_id: str) -> bool:
    chapter_dir = _chapters_dir(doc_id) / chapter_id
    if not chapter_dir.exists():
        return False
    shutil.rmtree(chapter_dir)
    return True


# ---------- Regions ----------


def _regions_dir(doc_id: str, chapter_id: str) -> Path:
    return _chapters_dir(doc_id) / chapter_id / "regions"


def create_region(
    doc_id: str,
    chapter_id: str,
    *,
    page: int,
    bbox: list[float],
    tag: str,
    label: str = "",
) -> dict[str, Any]:
    region_id = uuid.uuid4().hex[:12]
    region = {
        "id": region_id,
        "chapter_id": chapter_id,
        "page": page,
        "bbox": bbox,
        "tag": tag,
        "label": label,
        "transcription_md": None,
        "transcribed_at": None,
        "transcribed_model": None,
        "created_at": _now_iso(),
    }
    _atomic_write_text(
        _regions_dir(doc_id, chapter_id) / f"{region_id}.json",
        json.dumps(region, indent=2, ensure_ascii=False),
    )
    return region


def list_regions(doc_id: str, chapter_id: str) -> list[dict[str, Any]]:
    root = _regions_dir(doc_id, chapter_id)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(root.iterdir()):
        if f.suffix == ".json":
            out.append(json.loads(f.read_text("utf-8")))
    out.sort(key=lambda r: (r.get("page", 0), r.get("created_at", "")))
    return out


def load_region(doc_id: str, chapter_id: str, region_id: str) -> dict[str, Any] | None:
    p = _regions_dir(doc_id, chapter_id) / f"{region_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))


def update_region(doc_id: str, chapter_id: str, region_id: str, **changes: Any) -> dict[str, Any] | None:
    region = load_region(doc_id, chapter_id, region_id)
    if region is None:
        return None
    region.update(changes)
    _atomic_write_text(
        _regions_dir(doc_id, chapter_id) / f"{region_id}.json",
        json.dumps(region, indent=2, ensure_ascii=False),
    )
    return region


def delete_region(doc_id: str, chapter_id: str, region_id: str) -> bool:
    p = _regions_dir(doc_id, chapter_id) / f"{region_id}.json"
    if not p.exists():
        return False
    p.unlink()
    return True


def move_region(
    doc_id: str, src_chapter_id: str, region_id: str, dst_chapter_id: str
) -> dict[str, Any] | None:
    region = load_region(doc_id, src_chapter_id, region_id)
    if region is None:
        return None
    region["chapter_id"] = dst_chapter_id
    dst_dir = _regions_dir(doc_id, dst_chapter_id)
    dst_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        dst_dir / f"{region_id}.json",
        json.dumps(region, indent=2, ensure_ascii=False),
    )
    src = _regions_dir(doc_id, src_chapter_id) / f"{region_id}.json"
    if src.exists():
        src.unlink()
    return region


# ---------- LLM audit log ----------


def llm_audit_path() -> Path:
    return get_settings().data_dir / "llm_audit.jsonl"


def append_llm_audit(entry: dict[str, Any]) -> dict[str, Any]:
    """Append a single LLM call record to the audit log (JSONL).

    The caller is responsible for assembling the entry; this only sets `id`
    and `timestamp` if missing and writes one JSON object per line.
    """
    entry = {
        "id": entry.get("id") or f"req_{uuid.uuid4().hex[:12]}",
        "timestamp": entry.get("timestamp") or _now_iso(),
        **{k: v for k, v in entry.items() if k not in ("id", "timestamp")},
    }
    p = llm_audit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_llm_audit() -> Iterator[dict[str, Any]]:
    p = llm_audit_path()
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------- Jobs ----------


def _job_path(job_id: str) -> Path:
    return _jobs_root() / f"{job_id}.json"


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    payload = {**payload, "id": job_id, "created_at": _now_iso(), "status": "queued"}
    _atomic_write_text(_job_path(job_id), json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    job = load_job(job_id)
    if job is None:
        raise KeyError(job_id)
    job.update(changes)
    _atomic_write_text(_job_path(job_id), json.dumps(job, indent=2, ensure_ascii=False))
    return job


def load_job(job_id: str) -> dict[str, Any] | None:
    p = _job_path(job_id)
    if not p.exists():
        return None
    return json.loads(p.read_text("utf-8"))
