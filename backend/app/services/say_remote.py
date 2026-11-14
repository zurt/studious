"""Client for the Mac speech helper (``app/say_helper.py``).

The helper wraps the Mac's `say` command behind a small HTTP API:

- ``GET /health`` -> ``{"ok": true, "service": "studious-say-helper", "version": 1}``
- ``GET /voices`` -> ``{"listing": "<raw output of say -v '?'>"}``
- ``POST /say`` with ``{"text", "voice"}`` -> the clip as ``audio/mp4`` bytes.

Only http(s) URLs are accepted. ``EngineError.unreachable`` tells a Mac that
could not be reached (asleep, helper not running, timeout) from a helper that
answered with an error.
"""
from __future__ import annotations

import contextlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("studious.say_remote")

CONNECT_TIMEOUT = 5  # seconds: health, voices
SAY_TIMEOUT = 45


class EngineError(Exception):
    """The helper is unreachable or answered with an error; the message says which."""

    def __init__(self, message: str, *, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


def _open(req: urllib.request.Request, timeout: float) -> bytes:
    """The one place that touches the network (tests replace it)."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked in _request
        return resp.read()


def _unreachable(base: str) -> EngineError:
    return EngineError(
        f"The Mac speech helper is not reachable at {base}. "
        "Start it on the Mac with `make say-helper` and check that the Mac is awake.",
        unreachable=True,
    )


def _request(
    base: str,
    path: str,
    *,
    body: Any = None,
    method: str = "GET",
    timeout: float = CONNECT_TIMEOUT,
) -> bytes:
    base = (base or "").strip().rstrip("/")
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        raise EngineError(f"The Mac speech helper URL {base!r} must start with http:// or https://")
    data = None
    headers: dict[str, str] = {}
    if method == "POST":
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        return _open(req, timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):
            raw = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
                detail = str(parsed.get("detail", raw)) if isinstance(parsed, dict) else raw
            except ValueError:
                detail = raw
        raise EngineError(f"The Mac speech helper answered {exc.code} to {path}: {detail[:200]}".strip()) from exc
    except TimeoutError as exc:
        log.warning("say_remote_timeout", extra={"url": base, "route": path})
        raise _unreachable(base) from exc
    except (urllib.error.URLError, OSError) as exc:
        log.warning("say_remote_unreachable", extra={"url": base, "error": str(exc)})
        raise _unreachable(base) from exc


def _json(raw: bytes, what: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise EngineError(f"The Mac speech helper returned something that is not JSON for {what}") from exc


def health(base: str) -> dict[str, Any]:
    data = _json(_request(base, "/health"), "/health")
    if not isinstance(data, dict) or not data.get("ok"):
        raise EngineError("The service at the helper URL did not answer like the Mac speech helper")
    return data


def voices(base: str) -> str:
    """The raw ``say -v '?'`` listing from the Mac."""
    data = _json(_request(base, "/voices"), "/voices")
    listing = data.get("listing") if isinstance(data, dict) else None
    if not isinstance(listing, str):
        raise EngineError("The Mac speech helper returned an unexpected /voices response")
    return listing


def say(base: str, text: str, voice: str) -> bytes:
    audio = _request(base, "/say", body={"text": text, "voice": voice}, method="POST", timeout=SAY_TIMEOUT)
    if not audio:
        raise EngineError("The Mac speech helper returned no audio")
    return audio
