"""A small HTTP helper that wraps the Mac's `say` command.

Run it on the Mac with ``make say-helper`` (``python -m app.say_helper``). The
Studious server, wherever it runs, reaches it through the ``say_remote`` speech
engine (``services/say_remote.py``). Standard library only; it needs no data
directory and no settings beyond ``STUDIOUS_SAY_HELPER_PORT``.

It binds to 127.0.0.1 only (default port 8766). To reach it from another
machine publish it on the tailnet, e.g. ``tailscale serve --tcp 8766
tcp://127.0.0.1:8766``; it never binds a public interface and has no
authentication of its own (the tailnet is the boundary).

Routes:

- ``GET /health`` -> ``{"ok": true, "service": "studious-say-helper", "version": 1}``
- ``GET /voices`` -> ``{"listing": "<raw output of say -v '?'>"}``; 503 when `say` is missing or fails.
- ``POST /say`` with ``{"text": str, "voice": str}`` -> ``audio/mp4`` bytes (an AAC .m4a).
  400 for a bad body, text or voice; 413 for a body over 16 KB; 502 when `say` fails.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .services import tts

log = logging.getLogger("studious.say_helper")

HOST = "127.0.0.1"
DEFAULT_PORT = 8766
VERSION = 1
MAX_BODY = 16 * 1024
LISTING_TTL = 30  # seconds the voice listing is reused between /say calls

_say_lock = threading.Lock()
_listing_cache: tuple[float, str] | None = None
Response = tuple[int, str, bytes]


def _json(status: int, payload: dict[str, Any]) -> Response:
    return status, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _listing(*, fresh: bool = False) -> str:
    """``say -v '?'`` output, reused for LISTING_TTL seconds. Errors from `say`
    propagate to the caller."""
    global _listing_cache
    now = time.monotonic()
    if not fresh and _listing_cache and now - _listing_cache[0] < LISTING_TTL:
        return _listing_cache[1]
    text = tts._voices_output()
    _listing_cache = (now, text)
    return text


def reset_cache() -> None:
    global _listing_cache
    _listing_cache = None


def handle_health() -> Response:
    return _json(200, {"ok": True, "service": "studious-say-helper", "version": VERSION})


def handle_voices() -> Response:
    try:
        listing = _listing(fresh=True)
    except Exception as exc:  # noqa: BLE001 - any failure of `say` is a 503
        log.warning("say_helper_voices_failed", extra={"error": str(exc)})
        return _json(503, {"detail": f"Could not list the voices (`say -v '?'`): {exc}"})
    if not listing.strip():
        return _json(503, {"detail": "`say` listed no voices (is this a Mac?)"})
    return _json(200, {"listing": listing})


def handle_say(body: bytes) -> Response:
    if len(body) > MAX_BODY:
        return _json(413, {"detail": f"request body is over {MAX_BODY} bytes"})
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        return _json(400, {"detail": "body must be a JSON object"})
    if not isinstance(data, dict):
        return _json(400, {"detail": "body must be a JSON object"})
    text, voice = data.get("text"), data.get("voice")
    if not isinstance(text, str) or not text.strip():
        return _json(400, {"detail": "text must be a non-empty string"})
    text = text.strip()
    if len(text) > tts.MAX_CHARS:
        return _json(400, {"detail": f"text is {len(text)} characters; the limit is {tts.MAX_CHARS}"})
    if not isinstance(voice, str) or not voice.strip():
        return _json(400, {"detail": "voice must be a non-empty string"})
    voice = voice.strip()
    try:
        listed = tts.voice_listed(_listing(), voice)
    except Exception as exc:  # noqa: BLE001
        return _json(503, {"detail": f"Could not list the voices (`say -v '?'`): {exc}"})
    if not listed:
        return _json(400, {"detail": f"{voice!r} is not a voice listed by `say -v '?'`"})
    tmp = Path(tempfile.mkdtemp(prefix="say-helper-"))
    try:
        with _say_lock:
            try:
                out = tts._say(text, tmp / "clip.m4a", voice)
            except tts.TtsError as exc:
                return _json(502, {"detail": str(exc)})
        return 200, "audio/mp4", out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "studious-say-helper"

    def _send(self, started: float, response: Response, chars: int = 0) -> None:
        status, ctype, payload = response
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        log.info(
            "say_helper_request",
            extra={
                "method": self.command,
                "path": self.path,
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "chars": chars,
                "bytes": len(payload),
            },
        )

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        started = time.monotonic()
        if self.path == "/health":
            self._send(started, handle_health())
        elif self.path == "/voices":
            self._send(started, handle_voices())
        else:
            self._send(started, _json(404, {"detail": "not found"}))

    def do_POST(self) -> None:  # noqa: N802
        started = time.monotonic()
        if self.path != "/say":
            self._send(started, _json(404, {"detail": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._send(started, _json(400, {"detail": "bad Content-Length"}))
            return
        if length > MAX_BODY:
            # The body is not read; the connection closes after the refusal.
            self.close_connection = True
            self._send(started, _json(413, {"detail": f"request body is over {MAX_BODY} bytes"}))
            return
        body = self.rfile.read(length)
        chars = 0
        try:
            sent = json.loads(body.decode("utf-8")).get("text")
            chars = len(sent) if isinstance(sent, str) else 0
        except Exception:  # noqa: BLE001 - only for the log line
            chars = 0
        self._send(started, handle_say(body), chars)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - silence http.server's stderr lines
        pass


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), Handler)


def main() -> None:
    from .middleware import StructuredFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        port = int(os.environ.get("STUDIOUS_SAY_HELPER_PORT") or DEFAULT_PORT)
    except ValueError:
        print("STUDIOUS_SAY_HELPER_PORT must be a number", file=sys.stderr)
        raise SystemExit(2) from None
    server = make_server(port)
    log.info("say_helper_listening", extra={"host": HOST, "port": port})
    print(f"studious say helper listening on http://{HOST}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
