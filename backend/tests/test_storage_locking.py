"""Concurrency guarantees of the JSON storage layer."""
from __future__ import annotations

import contextlib
import threading
from pathlib import Path

from app.services import storage

N = 24


def _touch(p: Path) -> Path:
    p.write_bytes(b"x")
    return p


def _fixture(tmp: Path) -> tuple[str, str, str]:
    doc = storage.create_document(
        name="d", source_type="image", page_count=1, original_path=_touch(tmp / "x.png")
    )
    ch = storage.create_chapter(doc["id"], title="c", page_start=1, page_end=1)
    reg = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="other")
    return doc["id"], ch["id"], reg["id"]


def _run_threads(target, n: int = N) -> list[BaseException]:
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def wrap(i: int) -> None:
        try:
            barrier.wait()
            target(i)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _temp_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.name.endswith(".tmp")]


def test_concurrent_update_region_loses_nothing(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    errors = _run_threads(lambda i: storage.update_region(doc, ch, reg, **{f"f{i}": i}))
    assert errors == []
    region = storage.load_region(doc, ch, reg)
    assert all(region[f"f{i}"] == i for i in range(N))
    assert _temp_files(isolated_data_dir) == []


def test_concurrent_update_job_loses_nothing(isolated_data_dir):
    job = storage.create_job({"job_type": "t"})
    errors = _run_threads(lambda i: storage.update_job(job["id"], **{f"f{i}": i}))
    assert errors == []
    loaded = storage.load_job(job["id"])
    assert all(loaded[f"f{i}"] == i for i in range(N))


def test_concurrent_completion_upserts_keep_every_index(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    errors = _run_threads(
        lambda i: storage.upsert_exercise_completion_entry(doc, ch, reg, i, {"answer": str(i)})
    )
    assert errors == []
    completions = storage.load_exercise_completion(doc, ch, reg)["completions"]
    assert sorted(completions, key=int) == [str(i) for i in range(N)]


def test_concurrent_same_file_writes_leave_no_temp_and_no_listing(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    path = storage._region_path(doc, ch, reg)
    listed: list[int] = []

    def writer(i: int) -> None:
        for _ in range(5):
            storage._atomic_write_text(path, f'{{"id": "{reg}", "page": {i}}}')
            listed.append(len(storage.list_regions(doc, ch)))

    assert _run_threads(writer) == []
    assert set(listed) == {1}
    assert _temp_files(isolated_data_dir) == []
    assert [r["id"] for r in storage.list_regions(doc, ch)] == [reg]


def test_failed_write_cleans_up_temp(isolated_data_dir, monkeypatch):
    target = isolated_data_dir / "x" / "a.json"

    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(storage.os, "replace", boom)
    with contextlib.suppress(OSError):
        storage._atomic_write_text(target, "{}")
    assert _temp_files(isolated_data_dir) == []


def test_temp_file_is_not_a_record(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    rdir = storage._regions_dir(doc, ch)
    (rdir / f".{reg}.json.abc.tmp").write_text("{not json", encoding="utf-8")
    tdir = storage.document_dir(doc) / "transcriptions"
    (tdir / ".0001.json.abc.tmp").write_text("{", encoding="utf-8")
    assert len(storage.list_regions(doc, ch)) == 1
    assert storage.transcribed_pages(doc) == []


def test_locked_is_reentrant_with_updates(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    with storage.locked():
        with storage.locked():
            r = storage.load_region(doc, ch, reg)
            storage.update_region(doc, ch, reg, label=r["label"] + "x")
            storage.update_chapter(doc, ch, title="t2")
        assert storage.delete_region(doc, ch, reg) is True
    assert storage.load_chapter(doc, ch)["title"] == "t2"


def test_locked_blocks_other_threads(isolated_data_dir):
    doc, ch, reg = _fixture(isolated_data_dir)
    done = threading.Event()

    def other() -> None:
        storage.update_region(doc, ch, reg, label="other")
        done.set()

    with storage.locked():
        t = threading.Thread(target=other)
        t.start()
        assert not done.wait(0.2)
    t.join(2)
    assert done.is_set()
