import hashlib
import json
import threading
import time

import pytest

from app import jobs, storage
from app.db import blobs
from app.db import connection as db
from app.db.legacy import _legacy_clean_key

FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@pytest.fixture
def data_dir(tmp_path):
    storage.init(tmp_path)
    yield tmp_path
    db.close()


def _page(original: str, **extra) -> dict:
    return {"id": storage.new_id(), "original": original, "width": 100, "height": 140, "source": "photo",
            "corners": FULL, "detected": FULL, "rotation": 0, "filter": "enhanced", **extra}


def test_document_roundtrip(data_dir):
    doc = storage.create_doc("Scan 2026-01-01 10-00", "default")
    sha = blobs.put(b"fake jpeg", "jpg")
    lines = [{"text": "Hallo", "conf": 0.9, "bbox": [1, 2, 3, 4]}]
    with storage.editing(doc["id"]) as d:
        d["pages"] = [_page(sha, lines=lines), _page(sha)]
        d["outputs"] = {"scan": blobs.put(b"%PDF fake", "pdf")}
    loaded = storage.load_doc(doc["id"])
    assert loaded["name_source"] == "default"
    assert [p["original"] for p in loaded["pages"]] == [sha, sha]
    assert loaded["pages"][0]["lines"] == lines and loaded["pages"][1]["lines"] is None
    assert blobs.path(loaded["outputs"]["scan"]).read_bytes() == b"%PDF fake"
    # Reorder and drop a page.
    with storage.editing(doc["id"]) as d:
        d["pages"] = [d["pages"][1]]
    assert len(storage.load_doc(doc["id"])["pages"]) == 1
    assert [d["id"] for d in storage.list_docs()] == [doc["id"]]


def test_blobs_dedupe_and_gc(data_dir):
    a = blobs.put(b"same", "jpg")
    assert blobs.put(b"same", "jpg") == a == hashlib.sha256(b"same").hexdigest()
    orphan = blobs.put(b"orphan", "jpg")
    doc = storage.create_doc("x")
    with storage.editing(doc["id"]) as d:
        d["pages"] = [_page(a)]
    assert blobs.gc() == 0  # young blobs survive the grace period
    assert blobs.gc(grace=-1) == 1
    with pytest.raises(KeyError):
        blobs.path(orphan)
    assert blobs.path(a).exists()
    storage.delete_doc(doc["id"])
    assert blobs.gc(grace=-1) == 1 and not list((data_dir / "blobs").rglob("*.jpg"))


def test_concurrent_edits_do_not_lose_updates(data_dir):
    doc = storage.create_doc("x")
    with storage.editing(doc["id"]) as d:
        d["progress"] = {"step": "count", "done": 0, "total": 0}

    def bump():
        for _ in range(20):
            with storage.editing(doc["id"]) as d:
                d["progress"] = {**d["progress"], "done": d["progress"]["done"] + 1}

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert storage.load_doc(doc["id"])["progress"]["done"] == 160


def test_translation_and_preview_cache(data_dir):
    storage.cache_translations({"k1": "Hello", "k2": "World"})
    assert storage.cached_translations(["k1", "k2", "k3"]) == {"k1": "Hello", "k2": "World"}
    doc = storage.create_doc("x")
    with storage.editing(doc["id"]) as d:
        d["pages"] = [_page(blobs.put(b"img", "jpg"))]
    pid = storage.load_doc(doc["id"])["pages"][0]["id"]
    assert storage.cached_preview("pv1") is None
    storage.cache_preview("pv1", pid, b"jpegbytes")
    assert storage.cached_preview("pv1").read_bytes() == b"jpegbytes"
    storage.delete_doc(doc["id"])  # previews of deleted pages go too
    assert storage.cached_preview("pv1") is None


def test_legacy_json_documents_are_imported(tmp_path):
    # Old layout: data/docs/<id>/doc.json + pages/<pid>.jpg + <pid>.clean.jpg + PDFs.
    d = tmp_path / "docs" / "abc123def456"
    (d / "pages").mkdir(parents=True)
    (d / "pages" / "p1.jpg").write_bytes(b"original photo")
    (d / "pages" / "p1.clean.jpg").write_bytes(b"cleaned page")
    (d / "pages" / "p2.jpg").write_bytes(b"second photo")
    for f in ("scan.pdf", "translated.pdf", "side_by_side.pdf"):
        (d / f).write_bytes(b"%PDF " + f.encode())
    p1 = {"id": "p1", "file": "pages/p1.jpg", "width": 10, "height": 14, "source": "photo", "corners": FULL,
          "detected": FULL, "rotation": 0, "filter": "enhanced", "lines": [{"text": "Hallo", "conf": 1, "bbox": [0, 0, 1, 1]}]}
    p1["clean_key"] = p1["ocr_key"] = _legacy_clean_key(p1, jobs.SCAN_VERSION)
    p2 = {"id": "p2", "file": "pages/p2.jpg", "width": 10, "height": 14, "source": "photo", "corners": FULL,
          "detected": FULL, "rotation": 0, "filter": "enhanced", "ocr_key": "stale", "lines": [{"text": "alt"}]}
    (d / "doc.json").write_text(json.dumps({
        "id": "abc123def456", "name": "Scan 2026-10-03 13-27", "created": time.time(), "status": "done",
        "progress": None, "error": None, "pages": [p1, p2],
        "outputs": {"scan": "scan.pdf", "translated": "translated.pdf", "side_by_side": "side_by_side.pdf"},
        "tcache": {"somekey": "Hello"},
    }), "utf-8")

    storage.init(tmp_path)
    try:
        doc = storage.load_doc("abc123def456")
        assert doc["name_source"] == "default" and doc["status"] == "done"
        first, second = doc["pages"]
        assert blobs.path(first["original"]).read_bytes() == b"original photo"
        assert blobs.path(first["clean"]).read_bytes() == b"cleaned page"
        assert first["ocr_key"] == first["clean_key"] == jobs.clean_key(first)  # OCR cache still valid
        assert first["lines"][0]["text"] == "Hallo"
        assert second["ocr_key"] is None and second["lines"] is None and second["clean"] is None
        assert set(doc["outputs"]) == {"scan", "translated", "side_by_side"}
        assert storage.cached_translations(["somekey"]) == {"somekey": "Hello"}
        assert not (tmp_path / "docs").exists() and list(tmp_path.glob("docs.migrated-*"))
        storage.init(tmp_path)  # second start: nothing left to import, no error
        assert len(storage.list_docs()) == 1
    finally:
        db.close()
