from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


def render_pdf_to_pages(pdf_path: Path, out_dir: Path, dpi: int = 150) -> int:
    """Rasterize each page of ``pdf_path`` to ``out_dir/<NNNN>.png``.

    Returns the number of pages rendered.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        for i in range(page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(out_dir / f"{i + 1:04d}.png")
    return page_count


def copy_image_as_page(image_path: Path, out_dir: Path) -> int:
    """Convert an uploaded image to ``out_dir/0001.png`` and return ``1``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as im:
        im.convert("RGB").save(out_dir / "0001.png", format="PNG")
    return 1


def prepare_for_vlm(image_path: Path, max_edge: int = 1568) -> bytes:
    """Load a page image, downscale so the long edge <= ``max_edge``, return PNG bytes."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        long_edge = max(w, h)
        if long_edge > max_edge:
            scale = max_edge / float(long_edge)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def crop_region(image_path: Path, bbox: list[float], max_edge: int = 1568) -> bytes:
    """Crop a page image to a normalized bounding box and prepare for VLM.

    ``bbox`` is [x1, y1, x2, y2] where each value is a fraction (0.0–1.0)
    of the image dimensions.  Returns PNG bytes ready for VLM input.
    """
    x1, y1, x2, y2 = bbox
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        crop_box = (int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h))
        cropped = im.crop(crop_box)
        cw, ch = cropped.size
        long_edge = max(cw, ch)
        if long_edge > max_edge:
            scale = max_edge / float(long_edge)
            cropped = cropped.resize(
                (max(1, int(cw * scale)), max(1, int(ch * scale))), Image.LANCZOS
            )
        buf = io.BytesIO()
        cropped.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
