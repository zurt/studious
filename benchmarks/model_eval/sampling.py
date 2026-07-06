"""Pure stratified-sampling logic for building eval datasets.

Operates entirely on in-memory candidate dicts (as produced by store.py) —
no file I/O, no network. This is what test_model_eval.py exercises directly
to check determinism and shortfall handling.

Candidates are sorted by a stable id *before* any random.Random call, so the
same seed always yields the same selection regardless of on-disk iteration
order (directory listings, dict ordering, etc.).
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

# Default sampling quotas. A data structure (not hardcoded logic) so callers
# can override quotas per-source/per-tag without touching sampling code.
DEFAULT_QUOTAS: dict[str, dict[str, Any]] = {
    "textbook": {
        "region": {
            "exercises": 5,
            "grammar_points": 5,
            "vocab_list": 4,
            "reading_passage": 3,
            "instructions": 1,
        },
        "page": 4,
    },
    "workbook": {
        "region": {
            "exercises": 7,
        },
        "page": 2,
    },
}


@dataclass
class SampleOutcome:
    selected: list[dict]
    shortfall: int
    candidate_count: int
    quota: int


@dataclass
class StratumStats:
    stratum: str
    candidate_count: int
    quota: int
    selected_count: int
    shortfall: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stratum": self.stratum,
            "candidate_count": self.candidate_count,
            "quota": self.quota,
            "selected_count": self.selected_count,
            "shortfall": self.shortfall,
        }


@dataclass
class SelectionResult:
    selected_regions: list[dict] = field(default_factory=list)
    selected_pages: list[dict] = field(default_factory=list)
    stratum_stats: list[StratumStats] = field(default_factory=list)


def sample_stratum(rng: random.Random, candidates: list[dict], quota: int) -> SampleOutcome:
    """Sample `quota` items from `candidates` (already stably sorted).

    If there are fewer candidates than the quota, take all of them and
    report the shortfall rather than failing.
    """
    candidates = list(candidates)
    n = len(candidates)
    if quota <= 0:
        return SampleOutcome([], 0, n, quota)
    if n <= quota:
        return SampleOutcome(candidates, quota - n, n, quota)
    selected = rng.sample(candidates, quota)
    return SampleOutcome(selected, 0, n, quota)


def sample_pages_avoiding_used(
    rng: random.Random,
    candidates: list[dict],
    quota: int,
    used_keys: set[Any],
    key: Callable[[dict], Any],
) -> SampleOutcome:
    """Sample pages, softly preferring ones not already used by a sampled region.

    If preferred (unused) candidates can't fill the quota, fall back to used
    candidates to fill the remainder rather than failing — this is a soft
    constraint per spec.
    """
    candidates = list(candidates)
    n = len(candidates)
    if quota <= 0:
        return SampleOutcome([], 0, n, quota)

    preferred = [c for c in candidates if key(c) not in used_keys]
    rest = [c for c in candidates if key(c) in used_keys]

    if len(preferred) >= quota:
        selected = rng.sample(preferred, quota)
        return SampleOutcome(selected, 0, n, quota)

    selected = list(preferred)
    remaining = quota - len(preferred)
    if len(rest) >= remaining:
        selected += rng.sample(rest, remaining)
        shortfall = 0
    else:
        selected += rest
        shortfall = remaining - len(rest)
    return SampleOutcome(selected, shortfall, n, quota)


def select_dataset(
    region_candidates: list[dict],
    page_candidates: list[dict],
    seed: int,
    quotas: dict[str, dict[str, Any]] | None = None,
) -> SelectionResult:
    """Stratified-sample regions then pages, deterministically for a given seed.

    `region_candidates` / `page_candidates` are dicts with at least: `id`
    (stable sort key), `source`, and (for regions) `tag`, `doc_id`, `page`.
    Strata are visited in a fixed order (sorted source, then sorted tag) so
    that the single shared `random.Random(seed)` instance produces the same
    sequence of draws run to run.
    """
    quotas = quotas if quotas is not None else DEFAULT_QUOTAS
    rng = random.Random(seed)

    selected_regions: list[dict] = []
    stats: list[StratumStats] = []

    for source in sorted(quotas.keys()):
        region_quotas: dict[str, int] = quotas[source].get("region", {})
        for tag in sorted(region_quotas.keys()):
            quota = region_quotas[tag]
            candidates = sorted(
                (c for c in region_candidates if c["source"] == source and c["tag"] == tag),
                key=lambda c: c["id"],
            )
            outcome = sample_stratum(rng, candidates, quota)
            selected_regions.extend(outcome.selected)
            stats.append(
                StratumStats(
                    f"{source}/region/{tag}",
                    outcome.candidate_count,
                    outcome.quota,
                    len(outcome.selected),
                    outcome.shortfall,
                )
            )

    used_pages_by_source: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for r in selected_regions:
        used_pages_by_source[r["source"]].add((r["doc_id"], r["page"]))

    selected_pages: list[dict] = []
    for source in sorted(quotas.keys()):
        quota = int(quotas[source].get("page", 0))
        candidates = sorted(
            (c for c in page_candidates if c["source"] == source),
            key=lambda c: c["id"],
        )
        used_keys = used_pages_by_source.get(source, set())
        outcome = sample_pages_avoiding_used(
            rng, candidates, quota, used_keys, key=lambda c: (c["doc_id"], c["page"])
        )
        selected_pages.extend(outcome.selected)
        stats.append(
            StratumStats(
                f"{source}/page",
                outcome.candidate_count,
                outcome.quota,
                len(outcome.selected),
                outcome.shortfall,
            )
        )

    return SelectionResult(selected_regions, selected_pages, stats)
