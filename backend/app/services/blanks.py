"""Canonical form for fill-in-the-blank placeholders.

Textbook blanks are printed underlines whose length varies and which may
wrap across lines. The VLM renders them inconsistently — `＿＿＿`, `______`,
markdown-escaped `\\_\\_\\_`, sometimes with runs of 10-30 characters — and
the breakdown model then copies whatever it was given. This module maps
every blank style to one canonical run so stored transcriptions,
breakdowns, and the UI all agree.

Full-width `＿` (U+FF3F) is the canonical character: unlike ASCII `_` it
is never interpreted by Markdown, so it needs no escaping and cannot pair
up into emphasis across a paragraph.
"""

from __future__ import annotations

import re

BLANK_CHAR = "＿"
BLANK = BLANK_CHAR * 5

# One "unit" is a full-width ＿, an ASCII _, or a markdown-escaped \_.
_UNIT = r"(?:＿|\\?_)"
# A run containing at least one ＿, or 3+ units (so `__bold__` and a lone
# `_` in a snake_case token are left alone).
_BLANK_RUN = re.compile(rf"{_UNIT}*＿{_UNIT}*|{_UNIT}{{3,}}")
# A stray escaped underscore that is not part of a blank (`snake\_case`).
_ESCAPED_UNDERSCORE = re.compile(r"\\_")


def normalize_blanks(text: str) -> str:
    """Collapse every blank-underline run to `BLANK`; unescape stray `\\_`.

    Idempotent. Only touches underscore-family characters, so surrounding
    Japanese text, furigana, and markdown structure pass through intact.
    """
    if not text or ("_" not in text and BLANK_CHAR not in text):
        return text
    text = _BLANK_RUN.sub(BLANK, text)
    return _ESCAPED_UNDERSCORE.sub("_", text)
