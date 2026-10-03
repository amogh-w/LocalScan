"""jobs.document_pages_text: reads every page for AI naming, reusing and storing the OCR."""
import cv2
import numpy as np
import pytest

from app import jobs, storage
from app.db import blobs
from app.db import connection as db

FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@pytest.fixture
def data_dir(tmp_path):
    storage.init(tmp_path)
    yield tmp_path
    db.close()


def _doc_with_pages(n: int) -> str:
    sha = blobs.put(cv2.imencode(".jpg", np.full((140, 100, 3), 255, np.uint8))[1].tobytes(), "jpg")
    doc = storage.create_doc("x")
    with storage.editing(doc["id"]) as d:
        d["pages"] = [{"id": storage.new_id(), "original": sha, "width": 100, "height": 140, "source": "photo",
                       "corners": FULL, "detected": FULL, "rotation": 0, "filter": "original"} for _ in range(n)]
    return doc["id"]


class FakeOcr:
    """Stand-in for PaddleOCR: every reading returns one line, numbered by call."""

    def __init__(self, on_call=None):
        self.calls = 0
        self.on_call = on_call

    def ocr(self, img):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls)
        return [{"text": f"reading {self.calls}", "conf": 1.0, "bbox": [0, 0, 50, 10]}]


def test_every_page_is_read_once_and_the_ocr_is_kept(data_dir, monkeypatch):
    doc_id = _doc_with_pages(4)  # more than the two pages naming used to look at
    ocr = FakeOcr()
    monkeypatch.setattr(jobs, "get_ocr", lambda: ocr)
    texts = jobs.document_pages_text(doc_id)
    assert texts == ["reading 1", "reading 2", "reading 3", "reading 4"]
    pages = storage.load_doc(doc_id)["pages"]
    assert all(p["ocr_key"] and p["lines"] and p["clean"] for p in pages)
    assert jobs.document_pages_text(doc_id) == texts and ocr.calls == 4  # stored OCR is reused, no new readings


def test_a_page_recropped_while_reading_keeps_the_edit_and_no_stale_ocr(data_dir, monkeypatch):
    doc_id = _doc_with_pages(3)

    def recrop_second_page(call: int):
        if call == 2:  # the user drags a corner while page 2 is being read
            with storage.editing(doc_id) as d:
                d["pages"][1]["corners"] = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]

    monkeypatch.setattr(jobs, "get_ocr", lambda: FakeOcr(recrop_second_page))
    assert len(jobs.document_pages_text(doc_id)) == 3
    pages = storage.load_doc(doc_id)["pages"]
    assert [bool(p["ocr_key"]) for p in pages] == [True, False, True]  # page 2's reading is for the old crop
    assert pages[1]["corners"][0] == [0.1, 0.1]                        # and the user's edit survived
