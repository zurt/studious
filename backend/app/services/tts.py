"""Speech for Anki cards from the Mac's built-in voice (`say`).

``synthesize`` writes a real AAC .m4a (``--file-format=m4af --data-format=aac``;
plain ``-o x.m4a`` would write AIFF data under an .m4a name) into
``data/audio/`` and returns it. Files are named by a hash of voice + text, so
a clip is made once. ``say`` is run with an argument list (no shell) and reads
the text from a temporary UTF-8 file (``-f``), so text beginning with ``-``
can never be taken for an option.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("studious.tts")

MAX_CHARS = 200
MIN_BYTES = 1024
SAY_TIMEOUT = 30  # seconds
_TAG_RE = re.compile(r"<[^>]*>")
_VOICE_OK_RE = re.compile(r"^[\w][\w .()\-]*$")
_LIST_LINE_RE = re.compile(r"^(.*?)\s{2,}[A-Za-z]{2,3}[_-][A-Za-z0-9]+\b")

_lock = threading.Lock()
_available: dict[str, bool] = {}


class TtsError(Exception):
    """Synthesis failed or is not possible; the message says why."""


def audio_dir() -> Path:
    return get_settings().data_dir / "audio"


def voice() -> str:
    return get_settings().tts_voice


def reset_cache() -> None:
    _available.clear()


def _voices_output() -> str:
    out = subprocess.run(
        ["say", "-v", "?"], capture_output=True, text=True, timeout=10, check=False, encoding="utf-8"
    )
    return out.stdout


def voice_listed(listing: str, name: str) -> bool:
    """Whether ``say -v '?'`` output lists the voice ``name``."""
    want = name.strip().casefold()
    for line in listing.splitlines():
        m = _LIST_LINE_RE.match(line)
        have = (m.group(1) if m else line.split("#")[0].strip()).strip().casefold()
        if have == want or have.startswith(want + " ("):
            return True
    return False


def is_available() -> bool:
    """macOS, `say` on PATH and the configured voice installed. Cached per voice."""
    name = voice()
    if name not in _available:
        ok = False
        if sys.platform == "darwin" and shutil.which("say") and _VOICE_OK_RE.match(name):
            try:
                ok = voice_listed(_voices_output(), name)
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("tts_probe_failed", extra={"error": str(exc)})
        _available[name] = ok
    return _available[name]


def clean_text(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def clip_path(text: str) -> Path:
    key = hashlib.sha256(f"{voice()}\0{text}".encode()).hexdigest()[:20]
    return audio_dir() / f"{key}.m4a"


def synthesize(text: str) -> Path:
    """The cached clip for ``text`` (HTML tags removed), made when missing."""
    text = clean_text(text)
    if not text:
        raise TtsError("nothing to speak")
    if len(text) > MAX_CHARS:
        raise TtsError(f"text is {len(text)} characters; the limit is {MAX_CHARS}")
    if not is_available():
        raise TtsError(f"the {voice()!r} voice is not available (needs macOS with `say`)")
    out = clip_path(text)
    if out.exists() and out.stat().st_size >= MIN_BYTES:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        if out.exists() and out.stat().st_size >= MIN_BYTES:
            return out
        fd_in, in_name = tempfile.mkstemp(suffix=".txt", dir=out.parent)
        fd_out, tmp_out = tempfile.mkstemp(suffix=".m4a", dir=out.parent)
        os.close(fd_out)
        try:
            with os.fdopen(fd_in, "w", encoding="utf-8") as fh:
                fh.write(text)
            args = [
                "say",
                "-v",
                voice(),
                "--file-format=m4af",
                "--data-format=aac",
                "-o",
                tmp_out,
                "-f",
                in_name,
            ]
            try:
                proc = subprocess.run(
                    args, capture_output=True, timeout=SAY_TIMEOUT, check=False
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise TtsError(f"say failed: {exc}") from exc
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", "replace").strip()
                raise TtsError(f"say exited with {proc.returncode}: {err}")
            if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) < MIN_BYTES:
                raise TtsError("say produced no usable audio")
            os.replace(tmp_out, out)
            log.info("tts_synthesized", extra={"chars": len(text), "bytes": out.stat().st_size})
            return out
        finally:
            for p in (in_name, tmp_out):
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(p)
