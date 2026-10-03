"""Creating new documents from a sorted batch: copies of pages, the original untouched."""
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
    folder = library.create_folder("Inbox")
    tag = library.create_tag("Tax")
    doc = storage.create_doc("Scan 2026-10-03 13-27", "default")
    with storage.editing(doc["id"]) as d:
        d["folder_id"] = folder["id"]
        d["pages"] = [{"id": storage.new_id(), "original": blobs.put(f"photo {n}".encode(), "jpg"), "clean": blobs.put(f"clean {n}".encode(), "jpg"),
                       "width": 100, "height": 140, "source": "photo", "corners": FULL, "detected": FULL,
                       "rotation": 0, "filter": "enhanced", "clean_key": f"ck{n}", "ocr_key": f"ck{n}",
                       "lines": [{"text": f"Seite {n}", "conf": 1.0, "bbox": [0, 0, 10, 10]}]} for n in (1, 2, 3)]
    library.set_tags(doc["id"], [tag["id"]])
    yield doc["id"]
    db.close()


def test_new_documents_hold_copies_of_the_pages_in_the_requested_order(source):
    before = storage.load_doc(source)
    p1, p2, p3 = (p["id"] for p in before["pages"])
    first, second = storage.create_documents_from_pages(source, [
        {"page_ids": [p3, p1], "name": "2026-09-17 LBV NRW - Repayment", "name_source": "ai"},
        {"page_ids": [p2]},
    ])
    assert first["name"] == "2026-09-17 LBV NRW - Repayment" and first["name_source"] == "ai"
    assert second["name"] == "Scan 2026-10-03 13-27 (part 2)"
    # Copies: new ids, same files, same OCR and crop, in the requested order.
    assert [p["lines"][0]["text"] for p in first["pages"]] == ["Seite 3", "Seite 1"]
    assert not {p["id"] for p in first["pages"]} & {p1, p2, p3}
    originals = {p["id"]: p for p in before["pages"]}
    assert first["pages"][0]["original"] == originals[p3]["original"] and first["pages"][0]["clean"] == originals[p3]["clean"]
    assert first["pages"][0]["ocr_key"] == originals[p3]["ocr_key"]
    # Folder and tags carry over; the new documents are drafts.
    assert first["folder_id"] == before["folder_id"] and [t["name"] for t in second["tags"]] == ["Tax"]
    assert first["status"] == "draft" and first["outputs"] == {}
    # The original is exactly as it was.
    assert storage.load_doc(source) == before


def test_a_bad_page_id_creates_nothing(source):
    page = storage.load_doc(source)["pages"][0]["id"]
    count = len(storage.list_docs())
    with pytest.raises(KeyError):
        storage.create_documents_from_pages(source, [{"page_ids": [page]}, {"page_ids": ["nope"]}])
    with pytest.raises(ValueError):
        storage.create_documents_from_pages(source, [{"page_ids": [page, page]}])
    assert len(storage.list_docs()) == count  # all or nothing


def test_deleting_the_new_documents_keeps_the_original_intact(source):
    ids = [p["id"] for p in storage.load_doc(source)["pages"]]
    created = storage.create_documents_from_pages(source, [{"page_ids": ids[:2]}, {"page_ids": ids[2:]}])
    for doc in created:  # what Undo does
        storage.delete_doc(doc["id"])
    blobs.gc(grace=-1)
    kept = storage.load_doc(source)
    assert len(kept["pages"]) == 3
    assert all(blobs.path(p["original"]).exists() and blobs.path(p["clean"]).exists() for p in kept["pages"])


def test_the_endpoints_propose_and_apply(source, monkeypatch):
    ids = [p["id"] for p in storage.load_doc(source)["pages"]]
    monkeypatch.setattr(documents.sort, "propose", lambda doc_id, split: {"groups": [], "unplaced": [], "split": split})
    assert documents.sort_pages(source, split=False)["split"] is False
    out = documents.apply_sort(source, documents.ApplySort(groups=[documents.SortGroup(page_ids=ids[:2], name="A"),
                                                                  documents.SortGroup(page_ids=ids[2:])]))
    assert [d["name"] for d in out["documents"]] == ["A", "Scan 2026-10-03 13-27 (part 2)"]
    folder = storage.load_doc(source)["folder_id"]
    assert folder and all(d["folder_id"] == folder for d in out["documents"])  # new documents stay in the folder
    with pytest.raises(HTTPException) as bad:
        documents.apply_sort(source, documents.ApplySort(groups=[documents.SortGroup(page_ids=["nope"])]))
    assert bad.value.status_code == 400
    # A document that is being processed cannot be sorted or split.
    storage.update_doc(source, status="processing")
    with pytest.raises(HTTPException) as busy:
        documents.sort_pages(source)
    assert busy.value.status_code == 409


def test_sorting_needs_two_pages(tmp_path):
    storage.init(tmp_path)
    try:
        doc = storage.create_doc("empty")
        with pytest.raises(HTTPException) as e:
            documents.sort_pages(doc["id"])
        assert e.value.status_code == 400
    finally:
        db.close()


def test_copied_pages_can_be_removed_from_the_source(source):
    ids = [p["id"] for p in storage.load_doc(source)["pages"]]
    new = documents.apply_sort(source, documents.ApplySort(groups=[documents.SortGroup(page_ids=ids[:2])]))["documents"][0]
    left = documents.remove_pages(source, documents.RemovePages(page_ids=ids[:2]))
    assert [p["id"] for p in left["pages"]] == ids[2:]
    # The new document keeps its pages and their files after the source let go of them.
    kept = storage.load_doc(new["id"])
    assert len(kept["pages"]) == 2 and all(blobs.path(p["original"]).exists() for p in kept["pages"])
    with pytest.raises(HTTPException):
        documents.remove_pages(source, documents.RemovePages(page_ids=["nope"]))
