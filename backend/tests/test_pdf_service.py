from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image

from app.services import pdf


def _make_pdf(path: Path, num_pages: int) -> None:
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 50), f"page {i + 1}")
    doc.save(path)
    doc.close()


def test_render_pdf_to_pages_writes_one_png_per_page(tmp_path: Path):
    pdf_path = tmp_path / "in.pdf"
    out_dir = tmp_path / "out"
    _make_pdf(pdf_path, num_pages=3)
    n = pdf.render_pdf_to_pages(pdf_path, out_dir, dpi=72)
    assert n == 3
    files = sorted(p.name for p in out_dir.iterdir())
    assert files == ["0001.png", "0002.png", "0003.png"]
    # Each is a real PNG.
    with Image.open(out_dir / "0001.png") as im:
        assert im.format == "PNG"


def test_copy_image_as_page_writes_single_rgb_png(tmp_path: Path):
    src = tmp_path / "in.png"
    out_dir = tmp_path / "out"
    # Use RGBA to confirm conversion to RGB.
    Image.new("RGBA", (40, 30), (255, 0, 0, 128)).save(src)
    n = pdf.copy_image_as_page(src, out_dir)
    assert n == 1
    out = out_dir / "0001.png"
    assert out.exists()
    with Image.open(out) as im:
        assert im.mode == "RGB"


def test_prepare_for_vlm_downscales_when_long_edge_exceeds_max(tmp_path: Path):
    src = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), (255, 255, 255)).save(src)
    data = pdf.prepare_for_vlm(src, max_edge=1000)
    with Image.open(io.BytesIO(data)) as im:
        assert max(im.size) == 1000
        # Aspect ratio preserved (width was longer).
        assert im.size[0] == 1000


def test_prepare_for_vlm_no_op_when_smaller(tmp_path: Path):
    src = tmp_path / "small.png"
    Image.new("RGB", (200, 100), (0, 0, 0)).save(src)
    data = pdf.prepare_for_vlm(src, max_edge=1568)
    with Image.open(io.BytesIO(data)) as im:
        assert im.size == (200, 100)


def test_prepare_for_vlm_converts_rgba_to_rgb(tmp_path: Path):
    src = tmp_path / "rgba.png"
    Image.new("RGBA", (50, 50), (10, 20, 30, 128)).save(src)
    data = pdf.prepare_for_vlm(src, max_edge=1568)
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "RGB"
