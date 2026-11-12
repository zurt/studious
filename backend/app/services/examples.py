"""Generated example sentences for vocab items (Kaishi style).

A store item may carry an item-level ``example``::

    {"sentence": "彼に会えて嬉しかった。", "surface": "嬉しかった",
     "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。",
     "gloss": "I was glad to be able to meet him.",
     "source": "generated", "model": "<model id>", "created_at": "<iso>"}

Plain text only; the ``<b>`` around the target word is added when an Anki
note is built (``wrap_surface``). ``generate_examples`` asks the configured
model for sentences in batches through the VLM provider's ``call_tool``
(structured output, cached instructions), validates every entry with
``validate_entry``, retries failures once with the reason for each, stores
what passes with ``store.update_item`` and audits every call under the
``example_sentences`` job type so it shows up in the cost summary.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from ..config import (
    EXAMPLE_SENTENCES_PROMPT,
    EXAMPLE_SENTENCES_TOOL_SCHEMA,
    get_settings,
)
from ..middleware import correlation_id_var
from ..providers import registry
from . import costs, llm_audit, preferences, store

log = logging.getLogger("studious.examples")

BATCH_SIZE = 20
JOB_TYPE = "example_sentences"
TOOL_NAME = "record_examples"
PROVIDER = "anthropic"
MAX_TOKENS = 8192
MIN_SENTENCE_CHARS = 6
MAX_SENTENCE_CHARS = 40
MAX_GLOSS_CHARS = 200

_KANJI = "㐀-䶿一-鿿豈-﫿々〆"
_KANJI_RE = re.compile(f"[{_KANJI}]")
_UNIT_RE = re.compile(f"([{_KANJI}]+)\\[([^\\[\\]]*)\\]")
_READING_RE = re.compile(r"^[ぁ-ゖァ-ヺー・]+$")
_JAPANESE_RE = re.compile("[　-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_BRACKETS = "()（）[]［］{}｛｝【】「」『』〈〉《》<>＜＞"
_BLANK_CHARS = "_＿□"
_ENDINGS = "。！？"
_SUFFIX_RE = re.compile(r"(?:する|な)$")


class ExamplesError(Exception):
    """Generation could not run; ``status`` is the HTTP status the API answers."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- Validation (pure) ----------


def headword_stem(headword: str) -> str:
    """The part of a headword that must show up in the sentence's surface.

    A trailing (する) / する / な is dropped (企画する -> 企画); then the first
    kanji run, or for a headword without kanji its first two characters."""
    word = re.sub(r"\s*[(（](?:する|な)[)）]\s*$", "", (headword or "").strip())
    trimmed = _SUFFIX_RE.sub("", word)
    word = trimmed or word
    m = _KANJI_RE.search(word)
    if m:
        return re.match(f"[{_KANJI}]+", word[m.start() :]).group(0)  # type: ignore[union-attr]
    return word[:2]


def validate_furigana(sentence: str, furi: str) -> str | None:
    """Reason the Anki-syntax furigana is wrong for ``sentence``, or None."""
    if not furi:
        return "furigana is empty"
    for m in _UNIT_RE.finditer(furi):
        if not _READING_RE.match(m.group(2)):
            return f"reading {m.group(2)!r} must be hiragana or katakana only"
    rest = _UNIT_RE.sub(lambda m: m.group(1), furi)
    if "[" in rest or "]" in rest:
        return "a reading is attached to something that is not a kanji run"
    if _KANJI_RE.search(_UNIT_RE.sub("", furi)):
        return "a kanji run has no reading"
    if rest.replace(" ", "") != sentence:
        return "furigana does not reduce to the sentence when readings and spaces are removed"
    return None


def validate_entry(entry: Any, headword: str) -> str | None:
    """Reason one returned entry is unusable for ``headword``, or None.
    Does not check the id (see ``validate_entries``)."""
    if not isinstance(entry, dict):
        return "entry is not an object"
    sentence, surface = entry.get("sentence"), entry.get("surface")
    furi, gloss = entry.get("furigana"), entry.get("gloss")
    if not all(isinstance(v, str) for v in (sentence, surface, furi, gloss)):
        return "sentence, surface, furigana and gloss must all be strings"
    if not MIN_SENTENCE_CHARS <= len(sentence) <= MAX_SENTENCE_CHARS:
        return f"sentence must be {MIN_SENTENCE_CHARS} to {MAX_SENTENCE_CHARS} characters, got {len(sentence)}"
    if sentence[-1] not in _ENDINGS:
        return "sentence must end with 。, ！ or ？"
    if any(c.isspace() for c in sentence):
        return "sentence contains whitespace"
    if any(c in _BRACKETS for c in sentence):
        return "sentence contains brackets or markup"
    if any(c in _BLANK_CHARS for c in sentence):
        return "sentence contains a blank"
    if _ASCII_LETTER_RE.search(sentence) and not _ASCII_LETTER_RE.search(headword or ""):
        return "sentence contains Latin letters"
    if not surface:
        return "surface is empty"
    if surface not in sentence:
        return "surface does not occur in the sentence"
    stem = headword_stem(headword)
    if stem and stem not in surface:
        return f"surface does not contain the headword's stem {stem!r}"
    reason = validate_furigana(sentence, furi)
    if reason:
        return reason
    gloss = gloss.strip()
    if not gloss:
        return "gloss is empty"
    if len(gloss) >= MAX_GLOSS_CHARS:
        return f"gloss must be under {MAX_GLOSS_CHARS} characters"
    if _JAPANESE_RE.search(gloss):
        return "gloss contains Japanese characters"
    return None


def validate_entries(
    entries: Any, headwords: dict[str, str]
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Split a model response into ({id: clean entry}, {id: reason}).

    ``headwords`` maps each requested id to its headword. Entries with an id
    that was not requested are ignored; an id returned more than once fails
    (it is ambiguous); a requested id with no entry fails."""
    ok: dict[str, dict[str, str]] = {}
    bad: dict[str, str] = {}
    entries = entries if isinstance(entries, list) else []
    counts: dict[str, int] = {}
    for e in entries:
        eid = e.get("id") if isinstance(e, dict) else None
        if isinstance(eid, str):
            counts[eid] = counts.get(eid, 0) + 1
    for e in entries:
        eid = e.get("id") if isinstance(e, dict) else None
        if not isinstance(eid, str) or eid not in headwords:
            continue
        if counts[eid] > 1:
            bad[eid] = "id returned more than once"
            continue
        reason = validate_entry(e, headwords[eid])
        if reason:
            bad[eid] = reason
        else:
            ok[eid] = {k: e[k].strip() if k == "gloss" else e[k] for k in ("sentence", "surface", "furigana", "gloss")}
    for eid in headwords:
        if eid not in ok and eid not in bad:
            bad[eid] = "no entry was returned for this word"
    return ok, bad


# ---------- <b> around the target word ----------


def wrap_surface(furi: str, surface: str) -> str:
    """HTML-escaped furigana string with the first occurrence of ``surface``
    (matched against the sentence the furigana reduces to) wrapped in <b>.

    The wrap covers whole kanji-run units, and the single space that
    separated its first unit from the preceding kana is dropped (Anki's
    furigana filter takes ``>`` as the boundary). Not found: no wrap."""
    tokens: list[tuple[str, str]] = []  # (raw text, plain text)
    pos = 0
    for m in _UNIT_RE.finditer(furi):
        tokens.extend((c, "" if c == " " else c) for c in furi[pos : m.start()])
        tokens.append((m.group(0), m.group(1)))
        pos = m.end()
    tokens.extend((c, "" if c == " " else c) for c in furi[pos:])
    plain = "".join(p for _, p in tokens)
    idx = plain.find(surface) if surface else -1
    if idx < 0:
        return html.escape(furi, quote=False)
    end = idx + len(surface)
    first = last = None
    off = 0
    for i, (_, p) in enumerate(tokens):
        if p and first is None and off <= idx < off + len(p):
            first = i
        if p and off < end <= off + len(p):
            last = i
        off += len(p)
    if first is None or last is None:
        return html.escape(furi, quote=False)
    pre = "".join(r for r, _ in tokens[:first])
    inner = "".join(r for r, _ in tokens[first : last + 1])
    post = "".join(r for r, _ in tokens[last + 1 :])
    pre = pre[:-1] if pre.endswith(" ") else pre
    post = post[1:] if post.startswith(" ") else post
    esc = lambda s: html.escape(s, quote=False)  # noqa: E731
    return f"{esc(pre)}<b>{esc(inner)}</b>{esc(post)}"


# ---------- Generation ----------


def _word_payload(item: dict[str, Any], problem: str | None = None) -> dict[str, Any]:
    word: dict[str, Any] = {
        "id": item["id"],
        "headword": item.get("headword") or "",
        "reading": item.get("reading") or "",
        "meaning": item.get("meaning") or "",
        "pos": item.get("pos") or [],
    }
    if problem:
        word["problem"] = problem
    return word


def _prompt(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"text": f"{EXAMPLE_SENTENCES_PROMPT}\n\n", "cache": True},
        {"text": f"<words>\n{json.dumps(words, ensure_ascii=False, indent=1)}\n</words>"},
    ]


class _Totals:
    def __init__(self) -> None:
        self.calls = 0
        self.errors = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.cost_usd, 6),
        }


def _call(provider: Any, words: list[dict[str, Any]], config: dict[str, Any], totals: _Totals) -> Any:
    """One audited call_tool. Returns the response's `examples`; raises on failure."""
    t0 = time.monotonic()
    totals.calls += 1
    try:
        result = provider.call_tool(_prompt(words), TOOL_NAME, EXAMPLE_SENTENCES_TOOL_SCHEMA, config)
    except Exception as exc:
        totals.errors += 1
        llm_audit.record(
            provider=PROVIDER,
            model=str(config.get("model")),
            job_type=JOB_TYPE,
            status="error",
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
            correlation_id=correlation_id_var.get(""),
        )
        raise
    entry = llm_audit.record(
        provider=PROVIDER,
        model=result.meta.get("model") or config.get("model"),
        job_type=JOB_TYPE,
        status="success",
        duration_ms=int((time.monotonic() - t0) * 1000),
        correlation_id=correlation_id_var.get(""),
        **llm_audit.extract_usage(result.meta),
        **llm_audit.extract_provenance(result.meta),
    )
    totals.input_tokens += entry.get("input_tokens") or 0
    totals.output_tokens += entry.get("output_tokens") or 0
    totals.cost_usd += costs.estimate_cost(entry) or 0.0
    return result.tool_input.get("examples")


def _store_example(item_id: str, entry: dict[str, str], model: str) -> dict[str, Any] | None:
    example = {
        **entry,
        "source": "generated",
        "model": model,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return example if store.update_item("vocab", item_id, example=example) else None


def generate_examples(item_ids: list[str], *, force: bool = False) -> dict[str, Any]:
    """Generate and store an example sentence for each vocab item.

    Returns ``{"items": [{"id", "status", "example"?, "reason"?}], "usage": {...}}``
    with status ``generated``, ``kept`` (already has one and not ``force``) or
    ``failed``. Raises ``ExamplesError`` (503) when the provider is not
    configured and (502) when every LLM call failed."""
    results: dict[str, dict[str, Any]] = {}
    todo: list[dict[str, Any]] = []
    for item_id in dict.fromkeys(item_ids):
        item = store.get_item("vocab", item_id)
        if item is None or item.get("deleted"):
            results[item_id] = {"id": item_id, "status": "failed", "reason": "vocab item not found"}
        elif item.get("example") and not force:
            results[item_id] = {"id": item_id, "status": "kept", "example": item["example"]}
        else:
            todo.append(item)

    totals = _Totals()
    if todo:
        try:
            provider = registry.get_vlm(PROVIDER)
        except Exception as exc:
            raise ExamplesError(503, str(exc)) from exc
        model = preferences.get_active_vlm_model()
        config = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "effort": get_settings().vlm_effort_examples,
        }
        batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        last_error: Exception | None = None
        failed_batches = 0
        for batch in batches:
            try:
                _run_batch(provider, batch, config, totals, results)
            except Exception as exc:  # noqa: BLE001 - reported per item below
                last_error = exc
                failed_batches += 1
                log.error("example_batch_failed", extra={"error": str(exc), "items": len(batch)})
                for item in batch:
                    results[item["id"]] = {
                        "id": item["id"],
                        "status": "failed",
                        "reason": f"LLM call failed: {exc}",
                    }
        if failed_batches == len(batches) and last_error is not None:
            raise ExamplesError(502, f"Example sentence generation failed: {last_error}") from last_error

    ordered = [results[i] for i in dict.fromkeys(item_ids)]
    log.info(
        "examples_generated",
        extra={
            "generated": sum(1 for r in ordered if r["status"] == "generated"),
            "failed": sum(1 for r in ordered if r["status"] == "failed"),
            "kept": sum(1 for r in ordered if r["status"] == "kept"),
            **totals.as_dict(),
        },
    )
    return {"items": ordered, "usage": totals.as_dict()}


def _run_batch(
    provider: Any,
    batch: list[dict[str, Any]],
    config: dict[str, Any],
    totals: _Totals,
    results: dict[str, dict[str, Any]],
) -> None:
    headwords = {i["id"]: i.get("headword") or "" for i in batch}
    by_id = {i["id"]: i for i in batch}
    ok, bad = validate_entries(_call(provider, [_word_payload(i) for i in batch], config, totals), headwords)
    if bad:
        log.info("example_validation_retry", extra={"failures": bad})
        retry_words = [_word_payload(by_id[i], reason) for i, reason in bad.items()]
        try:
            ok2, bad2 = validate_entries(
                _call(provider, retry_words, config, totals), {i: headwords[i] for i in bad}
            )
        except Exception as exc:  # noqa: BLE001 - keep the first pass's successes
            log.error("example_retry_failed", extra={"error": str(exc)})
            ok2, bad2 = {}, {i: f"{reason} (retry call failed)" for i, reason in bad.items()}
        ok.update(ok2)
        bad = bad2
        if bad:
            log.warning("example_validation_dropped", extra={"failures": bad})
    for item_id, entry in ok.items():
        example = _store_example(item_id, entry, str(config["model"]))
        if example is None:
            results[item_id] = {"id": item_id, "status": "failed", "reason": "vocab item not found"}
        else:
            results[item_id] = {"id": item_id, "status": "generated", "example": example}
    for item_id, reason in bad.items():
        results[item_id] = {"id": item_id, "status": "failed", "reason": reason}


def remove_example(item_id: str) -> bool:
    """Clear a stored example. False when the item does not exist."""
    return store.update_item("vocab", item_id, example=None) is not None
