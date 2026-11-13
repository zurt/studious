"""Render the seed textbook (backend/seed/textbook.json) into an image-only PDF.

Run by hand on a Mac, only when the seed content changes:

    cd backend && uv run python scripts/build_seed.py

It lays each region's text out on a page image with Pillow (Hiragino, with
furigana drawn above the kanji that carry a `漢字(かな)` annotation), writes
each region's normalized bounding box [x1, y1, x2, y2] back into the manifest,
and assembles the pages into backend/seed/sample_textbook.pdf with PyMuPDF.
The PDF holds only page images: no font is embedded, so seeding and CI never
need the font. Commit the manifest and the PDF together.
"""
from __future__ import annotations

import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
MANIFEST = SEED_DIR / "textbook.json"

FONT_DIR = Path("/System/Library/Fonts")
FONT_REGULAR = FONT_DIR / "ヒラギノ角ゴシック W3.ttc"
FONT_BOLD = FONT_DIR / "ヒラギノ角ゴシック W6.ttc"

# Page geometry in pixels (the PDF page is sized so 300 dpi renders 1:1).
MARGIN_X = 100
CONTENT_TOP = 130
FOOTER_Y = 2020
BODY = 36  # base font size
RUBY = 18
REGION_PAD = 18  # bbox padding around the text of a region
GAP_REGIONS = 34

INK = 25
PAPER = 255
BAND = 236  # light panel fill
RULE = 170

RUBY_RE = re.compile(r"([一-鿿々〆ヶ]+)\(([ぁ-ゖー]+)\)")
HAS_JA = re.compile(r"[぀-ヿ一-鿿＀-￯　-〿]")
NO_LINE_START = set("、。，．・：；？！）」』】〕］｝〉》ゝゞー々ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ")


@dataclass
class Cell:
    base: str
    ruby: str | None
    bold: bool


class Fonts:
    def __init__(self) -> None:
        for p in (FONT_REGULAR, FONT_BOLD):
            if not p.exists():
                sys.exit(f"font not found: {p} (this script needs macOS Hiragino fonts)")
        self._cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}

    def get(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (bold, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size)
        return self._cache[key]


def parse_cells(line: str) -> list[Cell]:
    """Split a transcription line into cells: one per plain character, one per
    annotated kanji run. `**x**` marks bold."""
    cells: list[Cell] = []
    for i, part in enumerate(line.split("**")):
        bold = i % 2 == 1
        pos = 0
        for m in RUBY_RE.finditer(part):
            cells.extend(Cell(ch, None, bold) for ch in part[pos : m.start()])
            cells.append(Cell(m.group(1), m.group(2), bold))
            pos = m.end()
        cells.extend(Cell(ch, None, bold) for ch in part[pos:])
    return cells


def cell_width(fonts: Fonts, cell: Cell, size: int) -> float:
    bw = fonts.get(size, cell.bold).getlength(cell.base)
    if cell.ruby:
        rw = fonts.get(size // 2).getlength(cell.ruby)
        return max(bw, rw)
    return bw


def wrap_cells(fonts: Fonts, cells: list[Cell], size: int, width: float, indent: float) -> list[list[Cell]]:
    lines: list[list[Cell]] = [[]]
    x = 0.0
    for cell in cells:
        w = cell_width(fonts, cell, size)
        limit = width - (indent if len(lines) > 1 else 0)
        if lines[-1] and x + w > limit and cell.base not in NO_LINE_START:
            lines.append([])
            x = 0.0
        lines[-1].append(cell)
        x += w
    return lines


def wrap_words(font: ImageFont.FreeTypeFont, text: str, width: float) -> list[str]:
    out: list[str] = []
    cur = ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and font.getlength(trial) > width:
            out.append(cur)
            cur = word
        else:
            cur = trial
    out.append(cur)
    return out


class Page:
    def __init__(self, size: tuple[int, int], fonts: Fonts, number: int, running_title: str) -> None:
        self.w, self.h = size
        self.fonts = fonts
        self.img = Image.new("L", size, PAPER)
        self.draw = ImageDraw.Draw(self.img)
        self.y = CONTENT_TOP
        small = fonts.get(22)
        self.draw.text((MARGIN_X, 62), running_title, font=small, fill=110, anchor="ls")
        num = str(number)
        self.draw.text((self.w - MARGIN_X, 62), num, font=small, fill=110, anchor="rs")
        self.draw.line([(MARGIN_X, 78), (self.w - MARGIN_X, 78)], fill=RULE, width=2)
        self.draw.line([(MARGIN_X, FOOTER_Y + 30), (self.w - MARGIN_X, FOOTER_Y + 30)], fill=RULE, width=1)

    def banner(self, text: str) -> None:
        top, height = self.y, 150
        self.draw.rectangle([MARGIN_X - 40, top, self.w - MARGIN_X + 40, top + height], fill=60)
        cells = parse_cells(text)
        x = MARGIN_X
        size = 56
        base_y = top + height - 40
        for cell in cells:
            w = cell_width(self.fonts, cell, size)
            if cell.ruby:
                rf = self.fonts.get(size // 2)
                self.draw.text((x + w / 2, base_y - size - 6), cell.ruby, font=rf, fill=255, anchor="ms")
            self.draw.text((x + w / 2, base_y), cell.base, font=self.fonts.get(size, True), fill=255, anchor="ms")
            x += w
        self.y = top + height + 50

    def section(self, text: str) -> None:
        font = self.fonts.get(28, True)
        self.draw.text((MARGIN_X, self.y + 28), "■ " + text, font=font, fill=70, anchor="ls")
        self.y += 44

    def region(self, tag: str, lines: list[str]) -> list[float]:
        """Draw one region's text; return its normalized bbox."""
        x_left = MARGIN_X
        width = self.w - 2 * MARGIN_X
        pad = REGION_PAD
        inner_w = width - 2 * pad - 10
        # Dry run to measure, then draw (so a panel can be drawn behind the text).
        ops = self._layout(lines, inner_w)
        height = sum(op["h"] for op in ops) + 2 * pad
        top = self.y
        bottom = top + height
        if bottom > FOOTER_Y:
            raise SystemExit(f"region does not fit on page: bottom {bottom} > {FOOTER_Y} ({lines[0][:20]}…)")
        if tag in ("vocab_list", "grammar_points"):
            self.draw.rectangle([x_left, top, x_left + width, bottom], fill=BAND, outline=RULE, width=2)
        y = top + pad
        for op in ops:
            self._draw_op(op, x_left + pad + 5, y)
            y += op["h"]
        self.y = bottom + GAP_REGIONS
        return [
            round(x_left / self.w, 4),
            round(top / self.h, 4),
            round((x_left + width) / self.w, 4),
            round(bottom / self.h, 4),
        ]

    def _layout(self, lines: list[str], width: float) -> list[dict]:
        fonts = self.fonts
        ops: list[dict] = []
        for raw in lines:
            line = raw.rstrip()
            if not line:
                ops.append({"kind": "gap", "h": BODY * 0.55})
                continue
            if not HAS_JA.search(line):
                font = fonts.get(26)
                for part in wrap_words(font, line, width):
                    ops.append({"kind": "en", "text": part, "h": 26 * 1.5})
                continue
            m = re.match(r"^\d+\. ", line)
            indent = fonts.get(BODY).getlength(m.group(0)) if m else 0.0
            for i, cells in enumerate(wrap_cells(fonts, parse_cells(line), BODY, width, indent)):
                has_ruby = any(c.ruby for c in cells)
                ops.append(
                    {
                        "kind": "ja",
                        "cells": cells,
                        "indent": indent if i else 0.0,
                        "ruby": has_ruby,
                        "h": BODY * 1.3 + (RUBY + 6 if has_ruby else 6),
                    }
                )
        return ops

    def _draw_op(self, op: dict, x0: float, y: float) -> None:
        fonts = self.fonts
        if op["kind"] == "gap":
            return
        if op["kind"] == "en":
            self.draw.text((x0, y + 26 * 1.1), op["text"], font=fonts.get(26), fill=80, anchor="ls")
            return
        rb = RUBY + 6 if op["ruby"] else 6
        base_y = y + rb + BODY * 1.0
        x = x0 + op["indent"]
        for cell in op["cells"]:
            w = cell_width(fonts, cell, BODY)
            if cell.ruby:
                self.draw.text((x + w / 2, base_y - BODY * 0.95 - 3), cell.ruby, font=fonts.get(RUBY), fill=60, anchor="ms")
            self.draw.text((x + w / 2, base_y), cell.base, font=fonts.get(BODY, cell.bold), fill=INK, anchor="ms")
            x += w


def main() -> None:
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    fonts = Fonts()
    size = tuple(manifest["page_size"])
    regions = [(ch, r) for ch in manifest["chapters"] for r in ch["regions"]]
    n_pages = max(r["page"] for _, r in regions)
    pages: list[Page] = []
    for number in range(1, n_pages + 1):
        page = Page(size, fonts, number, manifest["title"])
        for ch in manifest["chapters"]:
            if ch["page_start"] == number:
                page.banner(ch["banner"])
        for _ch, r in regions:
            if r["page"] != number:
                continue
            if r.get("section"):
                page.section(r["section"])
            r["bbox"] = page.region(r["tag"], r["lines"])
        pages.append(page)

    pdf = fitz.open()
    pw, ph = manifest["pdf_page_pt"]
    for page in pages:
        buf = io.BytesIO()
        page.img.save(buf, format="PNG", optimize=True)
        pdf_page = pdf.new_page(width=pw, height=ph)
        pdf_page.insert_image(pdf_page.rect, stream=buf.getvalue())
    pdf.set_metadata({"title": manifest["title"]})
    out = SEED_DIR / manifest["pdf"]
    pdf.save(out, garbage=4, deflate=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {n_pages} pages) and bboxes in {MANIFEST.name}")


if __name__ == "__main__":
    main()
