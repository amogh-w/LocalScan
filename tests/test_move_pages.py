"""Moving pages out of a document into a new scan, and undoing it."""
import pytest
from fastapi import HTTPException

from app import library, storage
from app.api import documents
from app.db import blobs
from app.db import connection as db

FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@pytest.fixture
def source(tmp_path):
    storage.init(tmp_path)
    inbox = library.create_folder("Inbox")
    nested = library.create_folder("Tax", inbox["id"])
    tag = library.create_tag("Keep")
    doc = storage.create_doc("Scan A")
    with storage.editing(doc["id"]) as d:
        d["folder_id"] = inbox["id"]
        d["status"] = "done"
        d["pages"] = [{"id": f"p{n}", "original": blobs.put(f"photo {n}".encode(), "jpg"), "clean": None, "width": 10,
                       "height": 10, "corners": FULL, "lines": [{"text": f"Seite {n}", "conf": 1.0, "bbox": [0, 0, 1, 1]}]}
                      for n in range(6)]
    library.set_tags(doc["id"], [tag["id"]])
    yield {"id": doc["id"], "inbox": inbox["id"], "nested": nested["id"]}
    db.close()


def ids(doc_id):
    return [p["id"] for p in storage.load_doc(doc_id)["pages"]]


def test_pages_move_with_their_ids_and_the_source_closes_the_gaps(source):
    new, positions = storage.move_pages(source["id"], ["p3", "p1"])
    assert positions == [1, 3] and ids(new["id"]) == ["p1", "p3"]  # in document order
    assert ids(source["id"]) == ["p0", "p2", "p4", "p5"]
    assert new["name"] == "Scan A (pages 2, 4)" and new["folder_id"] == source["inbox"]
    assert [t["name"] for t in new["tags"]] == ["Keep"]
    assert storage.load_doc(new["id"])["pages"][0]["lines"][0]["text"] == "Seite 1"  # OCR travelled with it
    assert storage.load_doc(source["id"])["status"] == "draft" and new["status"] == "draft"


def test_folder_choices(source):
    other = storage.move_pages(source["id"], ["p0"], source["nested"])[0]
    unfiled = storage.move_pages(source["id"], ["p1"], None)[0]
    kept = storage.move_pages(source["id"], ["p2"])[0]
    assert (other["folder_id"], unfiled["folder_id"], kept["folder_id"]) == (source["nested"], None, source["inbox"])
    assert storage.move_pages(source["id"], ["p3", "p4"])[0]["name"].endswith("(pages 1-2)")  # p3 and p4 are the first two left


def test_bad_input_changes_nothing(source):
    before = ids(source["id"])
    count = len(storage.list_docs())
    for pages, folder in ((["nope"], storage.KEEP), (["p0", "p0"], storage.KEEP), (["p0"], "no-such-folder"), ([], storage.KEEP)):
        with pytest.raises((KeyError, ValueError)):
            storage.move_pages(source["id"], pages, folder)
    assert ids(source["id"]) == before and len(storage.list_docs()) == count


def test_undo_restores_exact_positions_and_removes_the_new_scan(source):
    new, positions = storage.move_pages(source["id"], ["p1", "p4", "p5"])
    back = storage.return_pages(new["id"], ["p1", "p4", "p5"], source["id"], positions)
    assert [p["id"] for p in back["pages"]] == [f"p{n}" for n in range(6)]
    assert new["id"] not in [d["id"] for d in storage.list_docs()]
    assert all(blobs.path(p["original"]).exists() for p in back["pages"])


def test_undo_after_the_new_scan_changed_is_refused_and_changes_nothing(source):
    new, positions = storage.move_pages(source["id"], ["p1", "p2"])
    storage.move_pages(new["id"], ["p2"])  # one of them moved on again
    with pytest.raises(KeyError):
        storage.return_pages(new["id"], ["p1", "p2"], source["id"], positions)
    assert ids(new["id"]) == ["p1"]


def test_the_endpoints_and_the_processing_guard(source):
    out = documents.move_pages(source["id"], documents.MovePages(page_ids=["p0"], folder_id=None))
    assert out["document"]["folder_id"] is None and len(out["source"]["pages"]) == 5
    documents.return_pages(source["id"], documents.ReturnPages(
        page_ids=["p0"], from_doc_id=out["document"]["id"], positions=out["positions"]))
    assert ids(source["id"])[0] == "p0"
    with pytest.raises(HTTPException) as e:
        documents.move_pages(source["id"], documents.MovePages(page_ids=["nope"]))
    assert e.value.status_code == 400
    storage.update_doc(source["id"], status="processing")
    with pytest.raises(HTTPException) as busy:
        documents.move_pages(source["id"], documents.MovePages(page_ids=["p0"]))
    assert busy.value.status_code == 409
