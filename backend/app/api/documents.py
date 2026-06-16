from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..config import get_settings
from ..services import pdf, storage

log = logging.getLogger("studious.api.documents")

router = APIRouter(prefix="/api/documents", tags=["documents"])


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _classify_upload(file: UploadFile) -> tuple[str, str]:
    """Return (suffix, source_type) for an upload, or raise 400."""
    if not file.filename:
        raise HTTPException(400, "missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix in PDF_SUFFIXES:
        return suffix, "pdf"
    if suffix in IMAGE_SUFFIXES:
        return suffix, "image"
    raise HTTPException(400, f"unsupported file type: {suffix!r}")


async def _save_upload_to_tmp(file: UploadFile, suffix: str) -> Path:
    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()
    return Path(tmp_name)


@router.post("")
async def upload_document(file: UploadFile = File(...)):
    suffix, source_type = _classify_upload(file)
    tmp = await _save_upload_to_tmp(file, suffix)

    meta = storage.create_document(
        name=file.filename,
        source_type=source_type,
        page_count=0,
        original_path=tmp,
    )

    doc_dir = storage.document_dir(meta["id"])
    pages_dir = doc_dir / "pages"
    original = doc_dir / meta["original_filename"]

    t0 = time.monotonic()
    try:
        if source_type == "pdf":
            page_count = pdf.render_pdf_to_pages(original, pages_dir, dpi=get_settings().pdf_render_dpi)
        else:
            page_count = pdf.copy_image_as_page(original, pages_dir)
    except Exception as exc:
        # A corrupt/unreadable file must not leave a zero-page document
        # behind in the library.
        shutil.rmtree(doc_dir, ignore_errors=True)
        log.error(
            "document_render_failed",
            extra={"doc_id": meta["id"], "source_type": source_type, "error": str(exc)},
        )
        raise HTTPException(400, f"could not render uploaded file: {exc}") from exc
    render_ms = int((time.monotonic() - t0) * 1000)
    log.info("document_uploaded", extra={"doc_id": meta["id"], "source_type": source_type, "page_count": page_count, "render_ms": render_ms})

    meta["page_count"] = page_count
    storage.save_document_meta(meta)
    return meta


@router.put("/{doc_id}/file")
async def reupload_document(doc_id: str, file: UploadFile = File(...)):
    meta = storage.load_document(doc_id)
    if meta is None:
        raise HTTPException(404, "document not found")
    suffix, source_type = _classify_upload(file)
    tmp = await _save_upload_to_tmp(file, suffix)

    doc_dir = storage.document_dir(doc_id)
    pages_dir = doc_dir / "pages"
    for old in doc_dir.glob("original.*"):
        old.unlink()
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    new_original = doc_dir / f"original{suffix}"
    shutil.move(str(tmp), new_original)

    t0 = time.monotonic()
    if source_type == "pdf":
        page_count = pdf.render_pdf_to_pages(new_original, pages_dir, dpi=get_settings().pdf_render_dpi)
    else:
        page_count = pdf.copy_image_as_page(new_original, pages_dir)
    render_ms = int((time.monotonic() - t0) * 1000)
    log.info("document_reuploaded", extra={"doc_id": doc_id, "source_type": source_type, "page_count": page_count, "render_ms": render_ms})

    meta["name"] = file.filename
    meta["source_type"] = source_type
    meta["page_count"] = page_count
    meta["original_filename"] = f"original{suffix}"
    storage.save_document_meta(meta)
    return meta


@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    doc_dir = storage.document_dir(doc_id)
    if not doc_dir.exists():
        raise HTTPException(404, "document not found")
    shutil.rmtree(doc_dir)
    log.info("document_deleted", extra={"doc_id": doc_id})
    return {"deleted": doc_id}


@router.get("")
def list_docs():
    return storage.list_documents()


@router.get("/{doc_id}")
def get_doc(doc_id: str):
    meta = storage.load_document(doc_id)
    if meta is None:
        raise HTTPException(404, "document not found")
    meta = dict(meta)
    meta["transcribed_pages"] = storage.transcribed_pages(doc_id)
    chapters = storage.list_chapters(doc_id)
    meta["chapters"] = chapters
    regions_total = 0
    regions_transcribed = 0
    for ch in chapters:
        for r in storage.list_regions(doc_id, ch["id"]):
            regions_total += 1
            if r.get("transcription_md"):
                regions_transcribed += 1
    meta["regions_total"] = regions_total
    meta["regions_transcribed"] = regions_transcribed
    return meta


@router.get("/{doc_id}/pages/{page}/image")
def get_page_image(doc_id: str, page: int):
    p = storage.page_image_path(doc_id, page)
    if not p.exists():
        raise HTTPException(404, "page not found")
    return FileResponse(p, media_type="image/png")


@router.get("/{doc_id}/pages/{page}/transcription")
def get_transcription(doc_id: str, page: int):
    t = storage.load_transcription(doc_id, page)
    if t is None:
        return JSONResponse(status_code=404, content={"detail": "no transcription yet"})
    return t
