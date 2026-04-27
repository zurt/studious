from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.services.pdf import crop_region


def _make_test_image(tmp_path: Path, width: int = 800, height: int = 1200) -> Path:
    img = Image.new("RGB", (width, height), color=(200, 200, 200))
    p = tmp_path / "page.png"
    img.save(p, format="PNG")
    return p


def test_crop_region_basic(tmp_path: Path):
    img_path = _make_test_image(tmp_path)
    bbox = [0.1, 0.2, 0.9, 0.8]
    result = crop_region(img_path, bbox)

    # Result should be valid PNG bytes
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"

    # Cropped size should be roughly (0.8*800) x (0.6*1200) = 640 x 720
    w, h = img.size
    assert 630 <= w <= 650
    assert 710 <= h <= 730


def test_crop_region_full_page(tmp_path: Path):
    img_path = _make_test_image(tmp_path)
    bbox = [0.0, 0.0, 1.0, 1.0]
    result = crop_region(img_path, bbox)
    img = Image.open(io.BytesIO(result))
    assert img.size == (800, 1200)


def test_crop_region_downscales_large(tmp_path: Path):
    img_path = _make_test_image(tmp_path, width=4000, height=3000)
    bbox = [0.0, 0.0, 1.0, 1.0]
    result = crop_region(img_path, bbox, max_edge=1568)
    img = Image.open(io.BytesIO(result))
    assert max(img.size) <= 1568


def test_crop_region_small_stays_same(tmp_path: Path):
    img_path = _make_test_image(tmp_path, width=400, height=300)
    bbox = [0.0, 0.0, 1.0, 1.0]
    result = crop_region(img_path, bbox, max_edge=1568)
    img = Image.open(io.BytesIO(result))
    assert img.size == (400, 300)
