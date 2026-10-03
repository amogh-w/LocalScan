"""Single background worker that turns a document's photos into the three PDFs."""
import hashlib
import json
import logging
import queue
import tempfile
import threading
import time
import traceback
from pathlib import Path

import numpy as np

from . import storage
from .db import blobs
from .config import settings
from .ocr.blocks import group_blocks
from .languages import ocr_code, scan_names, target_language
from .ocr.registry import get_ocr
from .render.pdf import RenderPage, build_scan_pdf, build_side_by_side_pdf, build_translated_pdf
from .scan.detect import FULL_IMAGE
from .scan.io import encode_jpeg, read_image
from .scan.warp import process_page
from .translate.registry import get_translator

log = logging.getLogger(__name__)

# Output kind -> download file name.
OUTPUTS = {
    "scan": "{name} (original).pdf",
    "translated": "{name} (translated).pdf",
    "side_by_side": "{name} (side-by-side).pdf",
}

_queue: "queue.Queue[str]" = queue.Queue()


# Bump when dewarping or filters change, so cached cleaned pages (and their OCR) are rebuilt.
SCAN_VERSION = 2


def clean_key(page: dict) -> str:
    key = [SCAN_VERSION, page["original"], page["corners"], page["rotation"], page["filter"]]
    if ocr_code():  # only a language with its own OCR model changes what is read
        key.append(ocr_code())
    raw = json.dumps(key)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# The stages of `process`, with the share of the whole job each is expected to take (for the overall percent).
STAGES = (("Cleaning and reading pages", 0.45), ("Translating", 0.40), ("Building PDFs", 0.15))
_started: dict[str, float] = {}


def _progress(doc_id: str, step: str, done: int, total: int, detail: str = "") -> None:
    """Record what the job is doing: the step, how far it is, a sentence of detail and the overall percent."""
    index = next(i for i, (name, _) in enumerate(STAGES) if name == step)
    before = sum(w for _, w in STAGES[:index])
    percent = round(100 * (before + STAGES[index][1] * min(1.0, done / max(1, total))))
    storage.update_doc(doc_id, status="processing", progress={
        "step": step, "done": done, "total": total, "detail": detail, "percent": percent,
        "stage": index + 1, "stages": len(STAGES), "elapsed": round(time.time() - _started.setdefault(doc_id, time.time()), 1),
    })


def _save(doc_id: str, **fields) -> None:
    """Write the worker's fields into the current document, leaving other edits (e.g. a rename) intact."""
    with storage.editing(doc_id) as doc:
        doc.update(fields)


def _uses_pdf_text(page: dict) -> bool:
    return bool(page.get("pdf_lines")) and page["corners"] == FULL_IMAGE and page["rotation"] % 360 == 0


class _OcrHolder:
    """Creates the OCR engine only when a page actually needs OCR."""

    def __init__(self) -> None:
        self.engine = None

    def get(self):
        self.engine = self.engine or get_ocr()
        return self.engine


def prepare_page(doc_id: str, page: dict, ocr: _OcrHolder) -> np.ndarray:
    """Dewarp + filter the page and OCR it, reusing cached results. Updates `page` in place."""
    key = clean_key(page)
    img = None
    if page.get("clean_key") == key and page.get("clean"):
        try:
            img = read_image(blobs.path(page["clean"]))
        except (KeyError, ValueError):
            img = None
    if img is None:
        img = process_page(read_image(blobs.path(page["original"])), page["corners"], page["rotation"], page["filter"])
        page["clean"] = blobs.put(encode_jpeg(img, 92), "jpg")
        page["clean_key"] = key
    if page.get("ocr_key") != key:
        page["lines"] = page["pdf_lines"] if _uses_pdf_text(page) else ocr.get().ocr(img)
        page["ocr_key"] = key
    return img


def read_pages(doc_id: str) -> list[dict]:
    """Every page of the document with its OCR, reading the pages that aren't read yet.

    Used by the AI helpers (naming, sorting) that run on request. The OCR is stored back, so translating
    later doesn't redo it. The returned pages are in document order and carry their `lines`.
    """
    pages = storage.load_doc(doc_id)["pages"]
    ocr = _OcrHolder()
    for page in pages:
        prepare_page(doc_id, page, ocr)
    with storage.editing(doc_id) as fresh:
        read = {p["id"]: p for p in pages}
        for p in fresh["pages"]:
            mine = read.get(p["id"])
            # Skip pages that were re-cropped or re-filtered while we were reading them.
            if mine and clean_key(p) == mine["clean_key"]:
                p.update(clean=mine["clean"], clean_key=mine["clean_key"], ocr_key=mine["ocr_key"], lines=mine["lines"])
    return pages


def document_pages_text(doc_id: str) -> list[str]:
    """Reading-order text of every page, OCR'ing pages that aren't read yet."""
    return page_texts(read_pages(doc_id))


def page_texts(pages: list[dict]) -> list[str]:
    """Reading-order text of each page ("" for pages without OCR text yet)."""
    return ["\n\n".join(b["text"] for b in group_blocks(p.get("lines") or [], i)) for i, p in enumerate(pages)]


def process(doc_id: str) -> None:
    doc = storage.load_doc(doc_id)
    pages = doc["pages"]
    if not pages:
        raise RuntimeError("Document has no pages")
    n = len(pages)
    _started[doc_id] = time.time()

    # 1. Dewarp + filter, and OCR (both cached per page).
    ocr = _OcrHolder()
    images = []
    for i, page in enumerate(pages):
        _progress(doc_id, "Cleaning and reading pages", i, n,
                  f"Page {i + 1} of {n}: straightening, cleaning and reading the text"
                  + (" (the first page also loads the text reader, about a minute)" if i == 0 else ""))
        images.append(prepare_page(doc_id, page, ocr))
        _save(doc_id, pages=pages)

    blocks_per_page = [group_blocks(p["lines"], i) for i, p in enumerate(pages)]

    # 2. Translate everything not already cached for this model.
    translator = get_translator()
    src, tgt = scan_names(), target_language().name
    tkey = translator.cache_key()

    def ck(text: str) -> str:
        return hashlib.sha1(f"{tkey}|{src}|{tgt}|{text}".encode()).hexdigest()[:20]

    all_blocks = [b for bl in blocks_per_page for b in bl]
    cache = storage.cached_translations(ck(b["text"]) for b in all_blocks)  # shared by all documents
    todo = [b for b in all_blocks if ck(b["text"]) not in cache]
    if todo:
        reused = len(all_blocks) - len(todo)
        note = f"{len(todo)} new paragraphs" + (f", {reused} reused from earlier translations" if reused else "")
        _progress(doc_id, "Translating", 0, 1, note)

        def on_progress(done: int, total: int) -> None:
            _progress(doc_id, "Translating", done, total, note)

        results = translator.translate_blocks(todo, src, tgt, on_progress)
        # Cache only real translations. A failed block (None) is shown untranslated this time and retried
        # on the next run, instead of pinning its source text in the cache for good.
        new = {ck(b["text"]): t for b, t in zip(todo, results) if t is not None}
        storage.cache_translations(new)
        cache.update(new)

    # 3. Render the three PDFs.
    _progress(doc_id, "Building PDFs", 0, 3, "Building the original PDF")
    render_pages = [
        RenderPage(img, bl, [cache.get(ck(b["text"]), b["text"]) for b in bl])  # untranslated: show the source
        for img, bl in zip(images, blocks_per_page)
    ]
    with tempfile.TemporaryDirectory(prefix="localscan-") as tmp:
        out = {k: Path(tmp) / f"{k}.pdf" for k in OUTPUTS}
        build_scan_pdf(render_pages, out["scan"])
        _progress(doc_id, "Building PDFs", 1, 3, "Building the translated PDF")
        build_translated_pdf(render_pages, out["translated"])
        _progress(doc_id, "Building PDFs", 2, 3, "Building the side-by-side PDF")
        build_side_by_side_pdf(out["scan"], out["translated"], out["side_by_side"])
        outputs = {k: blobs.put_file(f) for k, f in out.items()}

    _started.pop(doc_id, None)
    _save(doc_id, pages=pages, status="done", progress=None, error=None, outputs=outputs)
    storage.collect_garbage()  # previous PDFs and replaced cleaned pages


def _worker() -> None:
    while True:
        doc_id = _queue.get()
        try:
            process(doc_id)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            log.error("job %s failed\n%s", doc_id, traceback.format_exc())
            try:
                storage.update_doc(doc_id, status="error", progress=None, error=str(e))
            except KeyError:
                pass
        finally:
            _queue.task_done()


def enqueue(doc_id: str) -> None:
    storage.update_doc(doc_id, status="queued", progress=None, error=None)
    _queue.put(doc_id)


def start_worker() -> None:
    # Jobs interrupted by a restart go back to the queue.
    for doc in storage.list_docs():
        if doc["status"] in ("queued", "processing"):
            _queue.put(doc["id"])
    threading.Thread(target=_worker, daemon=True, name="scan-worker").start()
