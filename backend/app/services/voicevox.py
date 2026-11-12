"""Client for a VOICEVOX-compatible speech engine (VOICEVOX, AivisSpeech).

Both apps serve the same HTTP API on localhost. Every assumption about that
API lives in this module so it is easy to correct:

- ``GET /version`` -> a JSON string.
- ``GET /speakers`` -> ``[{"name", "speaker_uuid", "styles": [{"name", "id"}]}]``;
  a style's ``id`` is the ``speaker`` parameter.
- ``POST /audio_query?text=<text>&speaker=<id>`` (no body) -> a JSON query
  object with ``accent_phrases`` and a ``kana`` string (the reading in
  katakana with accent / phrase marks such as ``'``, ``/``, ``、``, ``_``).
- ``POST /synthesis?speaker=<id>`` with that JSON as the body -> WAV bytes.

Only http(s) URLs are accepted (a user-configured local address).
"""
from __future__ import annotations

import contextlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("studious.voicevox")

CONNECT_TIMEOUT = 5  # seconds: version, speakers, audio_query
SYNTHESIS_TIMEOUT = 30


class EngineError(Exception):
    """The engine is unreachable or answered with an error; the message says which."""


def _open(req: urllib.request.Request, timeout: float) -> bytes:
    """The one place that touches the network (tests replace it)."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked in _request
        return resp.read()


def _request(
    base: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
    method: str = "GET",
    timeout: float = CONNECT_TIMEOUT,
) -> bytes:
    base = (base or "").strip().rstrip("/")
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        raise EngineError(f"The speech engine URL {base!r} must start with http:// or https://")
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)  # percent-encodes Japanese text
    data = None
    headers: dict[str, str] = {}
    if method == "POST":
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        if body is not None:
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        return _open(req, timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            detail = exc.read().decode("utf-8", "replace")[:200]
        raise EngineError(f"The speech engine answered {exc.code} to {path}: {detail}".strip()) from exc
    except TimeoutError as exc:
        raise EngineError(f"The speech engine at {base} timed out on {path}") from exc
    except (urllib.error.URLError, OSError) as exc:
        log.warning("voicevox_unreachable", extra={"url": base, "error": str(exc)})
        raise EngineError(f"The speech engine is not reachable at {base}. Start VOICEVOX or AivisSpeech.") from exc


def _json(raw: bytes, what: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise EngineError(f"The speech engine returned something that is not JSON for {what}") from exc


def version(base: str) -> str:
    return str(_json(_request(base, "/version"), "/version"))


def speakers(base: str) -> list[dict[str, Any]]:
    """Flat list of ``{id, character, style, label}`` for every style."""
    data = _json(_request(base, "/speakers"), "/speakers")
    if not isinstance(data, list):
        raise EngineError("The speech engine returned an unexpected /speakers response")
    out: list[dict[str, Any]] = []
    for sp in data:
        for st in (sp or {}).get("styles") or []:
            if isinstance(st.get("id"), int):
                out.append(
                    {
                        "id": st["id"],
                        "character": sp.get("name", ""),
                        "style": st.get("name", ""),
                        "label": f"{sp.get('name', '')} — {st.get('name', '')}",
                    }
                )
    return out


def audio_query(base: str, text: str, speaker: int) -> dict[str, Any]:
    query = _json(
        _request(base, "/audio_query", params={"text": text, "speaker": speaker}, method="POST"),
        "/audio_query",
    )
    if not isinstance(query, dict):
        raise EngineError("The speech engine returned an unexpected /audio_query response")
    return query


def synthesis(base: str, query: dict[str, Any], speaker: int) -> bytes:
    wav = _request(
        base, "/synthesis", params={"speaker": speaker}, body=query, method="POST", timeout=SYNTHESIS_TIMEOUT
    )
    if not wav:
        raise EngineError("The speech engine returned no audio")
    return wav
