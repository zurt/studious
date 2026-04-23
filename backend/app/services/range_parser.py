from __future__ import annotations


def parse_pages(spec: str | None, page_count: int, *, allow_all: bool = True) -> list[int]:
    """Parse a page-range spec like ``"1-5, 8, 12-14"`` into a sorted, unique
    list of 1-indexed page numbers.

    The literal string ``"all"`` (case-insensitive) expands to every page when
    ``allow_all`` is True. Empty/None input is treated as ``"all"``.

    Raises ``ValueError`` with a precise message on bad input or out-of-range pages.
    """
    if page_count <= 0:
        raise ValueError("page_count must be positive")

    if spec is None or spec.strip() == "" or (allow_all and spec.strip().lower() == "all"):
        return list(range(1, page_count + 1))

    pages: set[int] = set()
    for chunk in spec.split(","):
        token = chunk.strip()
        if not token:
            continue
        if "-" in token:
            lo_s, hi_s = token.split("-", 1)
            lo_s, hi_s = lo_s.strip(), hi_s.strip()
            if not lo_s.isdigit() or not hi_s.isdigit():
                raise ValueError(f"invalid range: {token!r}")
            lo, hi = int(lo_s), int(hi_s)
            if lo < 1 or hi < 1:
                raise ValueError(f"page numbers must be >= 1: {token!r}")
            if lo > hi:
                raise ValueError(f"range start > end: {token!r}")
            if hi > page_count:
                raise ValueError(f"page {hi} out of range (1..{page_count})")
            pages.update(range(lo, hi + 1))
        else:
            if not token.isdigit():
                raise ValueError(f"invalid page: {token!r}")
            n = int(token)
            if n < 1 or n > page_count:
                raise ValueError(f"page {n} out of range (1..{page_count})")
            pages.add(n)

    if not pages:
        raise ValueError("no pages selected")
    return sorted(pages)
