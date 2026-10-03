"""Translating, re-translating and clearing one page or the whole document, and the translated page view."""
import pytest
from fastapi import HTTPException

from app import jobs, storage
from app.api import documents
from test_translation_cache import FakeOcr, FakeTranslator, _add_page, data_dir, setup  # noqa: F401 - fixtures


def two_pages(setup):
    doc_id, ocr, translator = setup
    _add_page(doc_id, 100)
    _add_page(doc_id, 120)
    first, second = (p["id"] for p in storage.load_doc(doc_id)["pages"])
    return doc_id, first, second, ocr, translator


def test_translating_one_page_reads_and_translates_only_that_page(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id, page_ids=[first])
    assert translator.sent == [["Erste Seite"]] and ocr.calls == 1
    doc = storage.load_doc(doc_id)
    assert doc["status"] == "draft" and doc["outputs"] == {}  # no PDFs from a single page
    status = jobs.translation_status(doc_id)
    assert status[first] == {"read": True, "total": 1, "done": 1}
    assert status[second] == {"read": False, "total": 0, "done": 0}  # not read yet


def test_translate_all_reuses_the_page_that_is_already_done(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id, page_ids=[first])
    jobs.process(doc_id)
    assert translator.sent == [["Erste Seite"], ["Zweite Seite"]]  # the first page is not sent again
    assert storage.load_doc(doc_id)["status"] == "done"


def test_translate_all_again_sends_everything_once_more(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id)
    jobs.process(doc_id, force=True)
    assert translator.sent == [["Erste Seite", "Zweite Seite"], ["Erste Seite", "Zweite Seite"]]
    jobs.process(doc_id)  # and the result is cached again
    assert len(translator.sent) == 2


def test_clearing_one_page_leaves_the_other_alone(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id)
    assert jobs.clear_translations(doc_id, [first]) == 1
    status = jobs.translation_status(doc_id)
    assert status[first]["done"] == 0 and status[second]["done"] == 1
    jobs.process(doc_id)
    assert translator.sent[1:] == [["Erste Seite"]]  # only the cleared page again


def test_clearing_everything_removes_the_pdfs_but_keeps_the_pages(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id)
    assert storage.load_doc(doc_id)["outputs"]
    out = documents.clear_translations(doc_id)
    assert out["outputs"] == {} and out["status"] == "draft" and len(out["pages"]) == 2
    assert all(s["done"] == 0 for s in jobs.translation_status(doc_id).values())
    jobs.process(doc_id)
    assert translator.sent[1:] == [["Erste Seite", "Zweite Seite"]]


def test_clearing_a_page_marks_a_finished_document_as_draft(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id)
    documents.clear_page_translation(doc_id, first)
    assert storage.load_doc(doc_id)["status"] == "draft"


def test_the_translated_page_view(setup):
    doc_id, first, second, ocr, translator = two_pages(setup)
    jobs.process(doc_id, page_ids=[first])
    shown = documents.translated_image(doc_id, first, 400)
    assert shown.media_type == "image/jpeg"
    with pytest.raises(HTTPException) as e:  # the second page was never read
        documents.translated_image(doc_id, second, 400)
    assert e.value.status_code == 404


def test_the_page_endpoints_queue_a_job_and_refuse_a_busy_document(setup, monkeypatch):
    doc_id, first, second, ocr, translator = two_pages(setup)
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda *a, **kw: queued.append((a, kw)))
    documents.translate_page(doc_id, second, force=True)
    assert queued == [((doc_id,), {"force": True, "page_ids": [second]})]
    assert storage.load_doc(doc_id)["status"] == "queued"
    with pytest.raises(HTTPException) as busy:
        documents.translate_page(doc_id, first)
    assert busy.value.status_code == 409
    with pytest.raises(HTTPException) as gone:
        storage.update_doc(doc_id, status="draft")
        documents.translate_page(doc_id, "nope")
    assert gone.value.status_code == 404


def test_the_real_queue_carries_force_and_the_pages(setup):
    """The endpoint test stubs enqueue; this one checks the queue itself."""
    doc_id, first, second, ocr, translator = two_pages(setup)
    while not jobs._queue.empty():
        jobs._queue.get_nowait()
    jobs.enqueue(doc_id, force=True, page_ids=[second])
    jobs.enqueue(doc_id)
    assert jobs._queue.get_nowait() == (doc_id, True, [second])
    assert jobs._queue.get_nowait() == (doc_id, False, None)
    assert storage.load_doc(doc_id)["status"] == "queued"
