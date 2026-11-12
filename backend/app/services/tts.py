"""Speech for Anki cards, from one of two engines.

- ``say``: the Mac's built-in voice. Written as a real AAC .m4a
  (``--file-format=m4af --data-format=aac``; plain ``-o x.m4a`` would write AIFF
  data under an .m4a name). The text goes through a temporary UTF-8 file
  (``-f``), so text beginning with ``-`` can never be read as an option.
- ``voicevox``: a VOICEVOX-compatible engine (VOICEVOX, AivisSpeech) on
  localhost (see ``voicevox.py``). Its WAV output is converted to AAC .m4a
  with ``afconvert`` when that exists, else kept as .wav.

The engine, URL and speaker come from preferences (Settings), falling back to
the ``STUDIOUS_TTS_*`` environment settings. ``synthesize`` returns a cached file
under ``data/audio/`` named by a hash of engine + voice/speaker + text, so
changing the voice never reuses old clips. ``is_available`` / ``status`` say
whether (and if not, why) clips can be made.
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
import time
import unicodedata
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import preferences, store, voicevox

log = logging.getLogger("studious.tts")

ENGINES = ("say", "voicevox")
MAX_CHARS = 200
MIN_BYTES = 1024
SAY_TIMEOUT = 30  # seconds
CONVERT_TIMEOUT = 30
AVAILABILITY_TTL = 10  # seconds; the engine app may be started or stopped any time
TEST_SENTENCE = "今日はいい天気ですね。"
_TAG_RE = re.compile(r"<[^>]*>")
_VOICE_OK_RE = re.compile(r"^[\w][\w .()\-]*$")
_LIST_LINE_RE = re.compile(r"^(.*?)\s{2,}[A-Za-z]{2,3}[_-][A-Za-z0-9]+\b")

_lock = threading.Lock()
_available: dict[Any, tuple[float, bool, str]] = {}


class TtsError(Exception):
    """Synthesis failed or is not possible; the message says why."""


# ---------- Configuration (preferences over environment) ----------


def audio_dir() -> Path:
    return get_settings().data_dir / "audio"


def engine() -> str:
    chosen = preferences.load().get("tts_engine")
    return chosen if chosen in ENGINES else get_settings().tts_engine


def url() -> str:
    chosen = preferences.load().get("tts_url")
    return chosen if isinstance(chosen, str) and chosen else get_settings().tts_url


def speaker() -> int | None:
    chosen = preferences.load().get("tts_speaker")
    if isinstance(chosen, int) and not isinstance(chosen, bool):
        return chosen
    return get_settings().tts_speaker


def voice() -> str:
    """The `say` voice name."""
    return get_settings().tts_voice


def reset_cache() -> None:
    _available.clear()


# ---------- Availability ----------


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


def _say_state() -> tuple[bool, str]:
    name = voice()
    if sys.platform != "darwin" or not shutil.which("say"):
        return False, "The Mac voice needs macOS with the `say` command."
    if not _VOICE_OK_RE.match(name):
        return False, f"{name!r} is not a usable voice name."
    try:
        if voice_listed(_voices_output(), name):
            return True, ""
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("tts_probe_failed", extra={"error": str(exc)})
    return False, f"The {name!r} voice is not installed (see `say -v '?'`)."


def _voicevox_state() -> tuple[bool, str]:
    base, sid = url(), speaker()
    if sid is None:
        return False, "A speaker must be chosen: pick one in Settings (or set STUDIOUS_TTS_SPEAKER)."
    try:
        voicevox.version(base)
        known = {s["id"] for s in voicevox.speakers(base)}
    except voicevox.EngineError as exc:
        return False, str(exc)
    if sid not in known:
        return False, f"Speaker {sid} is not offered by the engine at {base}; choose another in Settings."
    return True, ""


def _state() -> tuple[bool, str]:
    eng = engine()
    key: Any = (eng, voice()) if eng == "say" else (eng, url(), speaker())
    hit = _available.get(key)
    now = time.monotonic()
    if hit and (eng == "say" or now - hit[0] < AVAILABILITY_TTL):
        return hit[1], hit[2]
    ok, reason = _say_state() if eng == "say" else _voicevox_state()
    _available[key] = (now, ok, reason)
    return ok, reason


def is_available() -> bool:
    return _state()[0]


def unavailable_reason() -> str:
    ok, reason = _state()
    return "" if ok else reason


def speaker_label() -> str:
    """"Character — Style" of the chosen speaker, or the `say` voice name."""
    if engine() == "say":
        return voice()
    sid = speaker()
    try:
        for s in voicevox.speakers(url()):
            if s["id"] == sid:
                return s["label"]
    except voicevox.EngineError:
        pass
    return "" if sid is None else f"speaker {sid}"


def status() -> dict[str, Any]:
    ok, reason = _state()
    return {
        "available": ok,
        "engine": engine(),
        "voice": speaker_label() if ok else (voice() if engine() == "say" else ""),
        "url": url(),
        "speaker": speaker(),
        "reason": reason,
    }


# ---------- Reading check (VOICEVOX) ----------

_VOWELS: dict[str, str] = {}
for _row, _vowel in (
    ("あかさたなはまらわがざだばぱぁゎゎ", "a"),
    ("いきしちにひみりぎじぢびぴぃ", "i"),
    ("うくすつぬふむゆるぐずづぶぷぅゅゔ", "u"),
    ("えけせてねへめれげぜでべぺぇ", "e"),
    ("おこそとのほもよろをごぞどぼぽぉょ", "o"),
    ("ゃ", "a"),
):
    for _c in _row:
        _VOWELS[_c] = _vowel
_PARTICLES = str.maketrans("はへを", "わえお")  # the engine writes the spoken sound
_NON_KANA_RE = re.compile("[^ぁ-ゖー]")


def normalize_reading(reading: str) -> str:
    """Comparable form of a reading: katakana folded to hiragana, only kana and
    ー kept, particles は/へ/を as spoken (わ/え/お), and long vowels written one
    way (ー, おう after an o-sound, えい after an e-sound all become the doubled
    vowel): とうきょう == トーキョー."""
    text = store.kata_to_hira(unicodedata.normalize("NFKC", reading or ""))
    text = _NON_KANA_RE.sub("", text).translate(_PARTICLES)
    out: list[str] = []
    for ch in text:
        prev = _VOWELS.get(out[-1]) if out else None
        if ch == "ー" and prev:
            out.append({"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}[prev])
        elif ch == "う" and prev == "o":
            out.append("お")
        elif ch == "い" and prev == "e":
            out.append("え")
        else:
            out.append(ch)
    return "".join(out)


def kana_of_query(query: dict[str, Any]) -> str:
    """The query's ``kana`` reduced to plain katakana (marks dropped)."""
    return "".join(c for c in str(query.get("kana") or "") if "ァ" <= c <= "ヺ" or c == "ー")


def reading_matches(query: dict[str, Any], expected: str) -> bool:
    return normalize_reading(kana_of_query(query)) == normalize_reading(expected)


# ---------- Synthesis ----------


def clean_text(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _key(text: str, reading: str | None) -> str:
    eng = engine()
    who = voice() if eng == "say" else f"{url()}|{speaker()}"
    extra = (reading or "") if eng == "voicevox" else ""
    return hashlib.sha256(f"{eng}\0{who}\0{text}\0{extra}".encode()).hexdigest()[:20]


def media_type(path: Path) -> str:
    return "audio/wav" if path.suffix == ".wav" else "audio/mp4"


def _cached(key: str) -> Path | None:
    for ext in (".m4a", ".wav"):
        p = audio_dir() / f"{key}{ext}"
        if p.exists() and p.stat().st_size >= MIN_BYTES:
            return p
    return None


def _say(text: str, out: Path) -> Path:
    fd_in, in_name = tempfile.mkstemp(suffix=".txt", dir=out.parent)
    fd_out, tmp_out = tempfile.mkstemp(suffix=".m4a", dir=out.parent)
    os.close(fd_out)
    try:
        with os.fdopen(fd_in, "w", encoding="utf-8") as fh:
            fh.write(text)
        args = [
            "say", "-v", voice(), "--file-format=m4af", "--data-format=aac", "-o", tmp_out, "-f", in_name,
        ]
        try:
            proc = subprocess.run(args, capture_output=True, timeout=SAY_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TtsError(f"say failed: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise TtsError(f"say exited with {proc.returncode}: {err}")
        if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) < MIN_BYTES:
            raise TtsError("say produced no usable audio")
        os.replace(tmp_out, out)
        return out
    finally:
        for p in (in_name, tmp_out):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(p)


def _convert_to_m4a(wav: Path, out: Path) -> bool:
    """WAV -> AAC .m4a with afconvert. False (and no file) when it is missing or fails."""
    if not shutil.which("afconvert"):
        return False
    tmp = out.with_name(out.name + ".tmp.m4a")
    try:
        proc = subprocess.run(
            ["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(tmp)],
            capture_output=True,
            timeout=CONVERT_TIMEOUT,
            check=False,
        )
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < MIN_BYTES:
            log.warning("tts_convert_failed", extra={"returncode": proc.returncode})
            return False
        os.replace(tmp, out)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("tts_convert_failed", extra={"error": str(exc)})
        return False
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _voicevox(text: str, reading: str | None, key: str, report: dict[str, Any] | None) -> Path:
    base, sid = url(), speaker()
    assert sid is not None  # is_available() checked
    try:
        query = voicevox.audio_query(base, text, sid)
        if reading and not reading_matches(query, reading):
            log.info("tts_reading_corrected", extra={"text": text, "expected": reading, "got": kana_of_query(query)})
            query = voicevox.audio_query(base, reading, sid)
            if report is not None:
                report["corrected"] = True
        wav_bytes = voicevox.synthesis(base, query, sid)
    except voicevox.EngineError as exc:
        raise TtsError(str(exc)) from exc
    if len(wav_bytes) < MIN_BYTES:
        raise TtsError("the speech engine produced no usable audio")
    d = audio_dir()
    wav = d / f"{key}.wav"
    fd, tmp = tempfile.mkstemp(suffix=".wav", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(wav_bytes)
        os.replace(tmp, wav)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    m4a = d / f"{key}.m4a"
    if _convert_to_m4a(wav, m4a):
        wav.unlink()
        return m4a
    return wav


def synthesize(text: str, reading: str | None = None, *, report: dict[str, Any] | None = None) -> Path:
    """The cached clip for ``text`` (HTML tags removed), made when missing.

    ``reading`` (hiragana) is the reading the caller expects; with the VOICEVOX
    engine a different reading from the engine is replaced by this one, and
    ``report["corrected"]`` is set. The file is .m4a, or .wav when VOICEVOX
    output could not be converted (use ``media_type``)."""
    text = clean_text(text)
    if not text:
        raise TtsError("nothing to speak")
    if len(text) > MAX_CHARS:
        raise TtsError(f"text is {len(text)} characters; the limit is {MAX_CHARS}")
    ok, reason = _state()
    if not ok:
        raise TtsError(reason)
    key = _key(text, reading)
    hit = _cached(key)
    if hit:
        return hit
    audio_dir().mkdir(parents=True, exist_ok=True)
    with _lock:
        hit = _cached(key)
        if hit:
            return hit
        if engine() == "say":
            out = _say(text, audio_dir() / f"{key}.m4a")
        else:
            out = _voicevox(text, reading, key, report)
        log.info("tts_synthesized", extra={"engine": engine(), "chars": len(text), "bytes": out.stat().st_size})
        return out
