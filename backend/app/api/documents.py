from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..services import pdf, storage

router = APIRouter(prefix="/api/documents", tags=["documents"])


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


@router.post("")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix in PDF_SUFFIXES:
        source_type = "pdf"
    elif suffix in IMAGE_SUFFIXES:
        source_type = "image"
    else:
        raise HTTPException(400, f"unsupported file type: {suffix!r}")

    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    try:
        with tmp.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()

    meta = storage.create_document(
        name=file.filename,
        source_type=source_type,
        page_count=0,
        original_path=tmp,
    )

    doc_dir = storage.document_dir(meta["id"])
    pages_dir = doc_dir / "pages"
    original = doc_dir / meta["original_filename"]

    if source_type == "pdf":
        page_count = pdf.render_pdf_to_pages(original, pages_dir)
    else:
        page_count = pdf.copy_image_as_page(original, pages_dir)

    meta["page_count"] = page_count
    import json
    (doc_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")
    return meta


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
