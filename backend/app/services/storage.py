from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
