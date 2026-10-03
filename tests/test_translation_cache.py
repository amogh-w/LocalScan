"""jobs.process caches translations per paragraph: an added page only sends its own text to the model."""
import cv2
import numpy as np
import pytest

from app import jobs, storage
from app.db import blobs
from app.db import connection as db

FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
# Each page is a flat image of a different brightness; the fake OCR reads its text from that.
PAGES = {100: "Erste Seite", 120: "Zweite Seite", 140: "Dritte Seite"}


@pytest.fixture
def data_dir(tmp_path):
    storage.init(tmp_path)
    yield tmp_path
    db.close()


class FakeOcr:
    def __init__(self):
        self.calls = 0

    def ocr(self, img):
        self.calls += 1
        return [{"text": PAGES[round(float(img.mean()))], "conf": 1.0, "bbox": [0, 0, 50, 10]}]


class FakeTranslator:
    """Records which paragraphs reach the model. Paragraphs in `fail` come back as None (not translated)."""
    name = "fake"

    def __init__(self, fail=(), unchanged=()):
        self.sent: list[list[str]] = []
        self.fail, self.unchanged = set(fail), set(unchanged)

    def cache_key(self):
        return "fake:v1"

    def health(self):
        return True, ""

    def translate_blocks(self, blocks, src="German", tgt="English", on_progress=None):
        self.sent.append([b["text"] for b in blocks])
        return [None if b["text"] in self.fail else b["text"] if b["text"] in self.unchanged else f"EN {b['text']}"
                for b in blocks]


@pytest.fixture
def setup(data_dir, monkeypatch):
    ocr, translator = FakeOcr(), FakeTranslator()
    monkeypatch.setattr(jobs, "get_ocr", lambda: ocr)
    monkeypatch.setattr(jobs, "get_translator", lambda: translator)
    return storage.create_doc("x")["id"], ocr, translator


def _add_page(doc_id: str, shade: int) -> None:
    sha = blobs.put(cv2.imencode(".jpg", np.full((140, 100, 3), shade, np.uint8))[1].tobytes(), "jpg")
    with storage.editing(doc_id) as d:
        d["pages"].append({"id": storage.new_id(), "original": sha, "width": 100, "height": 140, "source": "photo",
                           "corners": FULL, "detected": FULL, "rotation": 0, "filter": "original"})


def test_adding_a_page_only_translates_the_new_page(setup):
    doc_id, ocr, translator = setup
    _add_page(doc_id, 100)
    _add_page(doc_id, 120)
    jobs.process(doc_id)
    assert translator.sent == [["Erste Seite", "Zweite Seite"]] and ocr.calls == 2

    _add_page(doc_id, 140)
    jobs.process(doc_id)
    assert translator.sent[1:] == [["Dritte Seite"]]  # the first two pages are not sent again ...
    assert ocr.calls == 3                              # ... nor read again

    jobs.process(doc_id)  # nothing changed: the model isn't called at all
    assert len(translator.sent) == 2
    assert set(storage.load_doc(doc_id)["outputs"]) == {"scan", "translated", "side_by_side"}


def test_translations_are_shared_between_documents(setup):
    doc_id, _, translator = setup
    _add_page(doc_id, 100)
    jobs.process(doc_id)
    other = storage.create_doc("y")["id"]
    _add_page(other, 100)  # a second copy of the same text
    jobs.process(other)
    assert translator.sent == [["Erste Seite"]]


def test_a_failed_paragraph_is_not_cached_and_is_retried(setup):
    doc_id, _, translator = setup
    translator.fail = {"Zweite Seite"}
    _add_page(doc_id, 100)
    _add_page(doc_id, 120)
    jobs.process(doc_id)  # still produces PDFs, with the source text where the model failed
    assert storage.load_doc(doc_id)["status"] == "done"

    translator.fail.clear()
    jobs.process(doc_id)
    assert translator.sent == [["Erste Seite", "Zweite Seite"], ["Zweite Seite"]]  # only the failed one again
    jobs.process(doc_id)
    assert len(translator.sent) == 2


def test_text_the_model_leaves_unchanged_is_a_real_translation(setup):
    doc_id, _, translator = setup
    translator.unchanged = {"Erste Seite"}  # e.g. a name or a reference number
    _add_page(doc_id, 100)
    jobs.process(doc_id)
    jobs.process(doc_id)
    assert translator.sent == [["Erste Seite"]]  # cached, not sent again
