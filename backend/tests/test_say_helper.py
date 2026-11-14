"""The Mac speech helper (say_helper) and its client (say_remote), over a real
loopback socket with `say` replaced by fakes."""
from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import say_helper
from app.services import say_remote, tts

LISTING = "Kyoko (Enhanced)    ja_JP    # こんにちは!\nSamantha            en_US    # Hello!\n"
AUDIO = b"\x00" * 3000


def _real_open(req, timeout):
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


@pytest.fixture
def helper(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_say(text: str, out: Path, voice: str) -> Path:
        calls.append((text, voice))
        out.write_bytes(AUDIO)
        return out

    say_helper.reset_cache()
    monkeypatch.setattr(tts, "_voices_output", lambda: LISTING)
    monkeypatch.setattr(tts, "_say", fake_say)
    server = say_helper.make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    # the real client opener, so these tests exercise the wire
    monkeypatch.setattr(say_remote, "_open", _real_open)
    yield base, calls
    server.shutdown()
    server.server_close()


def _post(base: str, path: str, data: bytes):
    req = urllib.request.Request(base + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status, resp.headers.get("Content-Type"), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type"), exc.read()


def test_binds_loopback_only():
    server = say_helper.make_server(0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_health_and_voices(helper):
    base, _ = helper
    assert say_remote.health(base) == {"ok": True, "service": "studious-say-helper", "version": 1}
    assert say_remote.voices(base) == LISTING


def test_say_returns_audio_and_logs_no_text(helper, caplog):
    base, calls = helper
    with caplog.at_level("INFO", logger="studious.say_helper"):
        audio = say_remote.say(base, "  こんにちは  ", "Kyoko")
    assert audio == AUDIO
    assert calls == [("こんにちは", "Kyoko")]  # "Kyoko" matches "Kyoko (Enhanced)"
    lines = [r for r in caplog.records if r.getMessage() == "say_helper_request"]
    assert lines and lines[-1].bytes == 3000
    assert "こんにちは" not in " ".join(r.getMessage() for r in caplog.records)


def test_say_content_type(helper):
    base, _ = helper
    status, ctype, body = _post(base, "/say", json.dumps({"text": "はい", "voice": "Kyoko"}).encode())
    assert (status, ctype, body) == (200, "audio/mp4", AUDIO)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[1, 2]",
        json.dumps({"text": "   ", "voice": "Kyoko"}).encode(),
        json.dumps({"text": "あ" * (tts.MAX_CHARS + 1), "voice": "Kyoko"}).encode(),
        json.dumps({"text": "はい"}).encode(),
        json.dumps({"text": "はい", "voice": "-o /etc/passwd"}).encode(),
        json.dumps({"text": "はい", "voice": "Nobody"}).encode(),
    ],
)
def test_say_validation_400(helper, payload):
    base, calls = helper
    status, _ctype, body = _post(base, "/say", payload)
    assert status == 400
    assert "detail" in json.loads(body)
    assert calls == []


def test_say_oversized_body_413(helper):
    base, calls = helper
    status, _, body = _post(base, "/say", b"x" * (say_helper.MAX_BODY + 1))
    assert status == 413 and "detail" in json.loads(body)
    assert calls == []


def test_say_failure_is_502(helper, monkeypatch):
    base, _ = helper

    def boom(text, out, voice):
        raise tts.TtsError("say exited with 1: nope")

    monkeypatch.setattr(tts, "_say", boom)
    status, _, body = _post(base, "/say", json.dumps({"text": "はい", "voice": "Kyoko"}).encode())
    assert status == 502 and "nope" in json.loads(body)["detail"]


def test_voices_503_when_say_fails(helper, monkeypatch):
    base, _ = helper

    def boom():
        raise OSError("no say")

    monkeypatch.setattr(tts, "_voices_output", boom)
    with pytest.raises(say_remote.EngineError) as err:
        say_remote.voices(base)
    assert not err.value.unreachable and "503" in str(err.value)


def test_unknown_route_404(helper):
    base, _ = helper
    with pytest.raises(say_remote.EngineError) as err:
        say_remote._request(base, "/nope")
    assert "404" in str(err.value)


def test_handlers_without_a_socket(monkeypatch):
    say_helper.reset_cache()
    monkeypatch.setattr(tts, "_voices_output", lambda: LISTING)

    def fake_say(text, out, voice):
        out.write_bytes(AUDIO)
        return out

    monkeypatch.setattr(tts, "_say", fake_say)
    assert say_helper.handle_health()[0] == 200
    assert json.loads(say_helper.handle_voices()[2])["listing"] == LISTING
    status, ctype, body = say_helper.handle_say(json.dumps({"text": "はい", "voice": "Kyoko"}).encode())
    assert (status, ctype, body) == (200, "audio/mp4", AUDIO)
    assert say_helper.handle_say(b"x" * (say_helper.MAX_BODY + 1))[0] == 413
    assert say_helper.handle_say(b"{}")[0] == 400


def test_say_calls_are_serialised(monkeypatch):
    say_helper.reset_cache()
    monkeypatch.setattr(tts, "_voices_output", lambda: LISTING)
    active = {"now": 0, "max": 0}
    guard = threading.Lock()

    def slow_say(text, out, voice):
        with guard:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        threading.Event().wait(0.05)
        out.write_bytes(AUDIO)
        with guard:
            active["now"] -= 1
        return out

    monkeypatch.setattr(tts, "_say", slow_say)
    body = json.dumps({"text": "はい", "voice": "Kyoko"}).encode()
    threads = [threading.Thread(target=say_helper.handle_say, args=(body,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1


# ---------- client error mapping ----------


def test_client_unreachable(monkeypatch):
    def refuse(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(say_remote, "_open", refuse)
    with pytest.raises(say_remote.EngineError) as err:
        say_remote.health("http://mac:8766")
    assert err.value.unreachable
    assert "make say-helper" in str(err.value) and "http://mac:8766" in str(err.value)
    assert "this Mac" not in str(err.value)


def test_client_timeout_is_unreachable(monkeypatch):
    def slow(req, timeout):
        raise TimeoutError()

    monkeypatch.setattr(say_remote, "_open", slow)
    with pytest.raises(say_remote.EngineError) as err:
        say_remote.say("http://mac:8766", "はい", "Kyoko")
    assert err.value.unreachable


def test_client_http_error_is_not_unreachable(monkeypatch):
    def bad(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO(b'{"detail": "say exited"}'))

    monkeypatch.setattr(say_remote, "_open", bad)
    with pytest.raises(say_remote.EngineError) as err:
        say_remote.say("http://mac:8766", "はい", "Kyoko")
    assert not err.value.unreachable and "502" in str(err.value) and "say exited" in str(err.value)


def test_client_rejects_non_http_url_and_bad_bodies(monkeypatch):
    with pytest.raises(say_remote.EngineError):
        say_remote.health("file:///etc/passwd")
    for raw, call in (
        (b"nope", say_remote.health),
        (b'{"ok": false}', say_remote.health),
        (b'{"x": 1}', say_remote.voices),
    ):
        monkeypatch.setattr(say_remote, "_open", lambda req, timeout, raw=raw: raw)
        with pytest.raises(say_remote.EngineError):
            call("http://mac:8766")
    monkeypatch.setattr(say_remote, "_open", lambda req, timeout: b"")
    with pytest.raises(say_remote.EngineError):
        say_remote.say("http://mac:8766", "はい", "Kyoko")


def test_client_timeouts_per_call(monkeypatch):
    seen = []

    def spy(req, timeout):
        seen.append(timeout)
        return b'{"ok": true, "listing": "x"}' if req.method == "GET" else b"audio"

    monkeypatch.setattr(say_remote, "_open", spy)
    say_remote.health("http://mac:8766")
    say_remote.voices("http://mac:8766")
    say_remote.say("http://mac:8766", "はい", "Kyoko")
    assert seen == [5, 5, 45]
