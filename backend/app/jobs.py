"""Single background worker that turns a document's photos into the three PDFs."""
import hashlib
import json
import logging
import queue
import threading
import traceback

import numpy as np

from . import storage
from .config import settings
from .ocr.blocks import group_blocks
from .ocr.registry import get_ocr
from .render.pdf import RenderPage, build_scan_pdf, build_side_by_side_pdf, build_translated_pdf
from .scan.detect import FULL_IMAGE
from .scan.io import read_image, write_image
from .scan.warp import process_page
from .translate.registry import get_translator

log = logging.getLogger(__name__)

OUTPUTS = {
    "scan": ("scan.pdf", "{name} (scan).pdf"),
    "translated": ("translated.pdf", "{name} (English).pdf"),
    "side_by_side": ("side_by_side.pdf", "{name} (side-by-side).pdf"),
}

_queue: "queue.Queue[str]" = queue.Queue()


# Bump when dewarping or filters change, so cached cleaned pages (and their OCR) are rebuilt.
SCAN_VERSION = 2


def clean_key(page: dict) -> str:
    raw = json.dumps([SCAN_VERSION, page["file"], page["corners"], page["rotation"], page["filter"]])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _progress(doc_id: str, step: str, done: int, total: int) -> None:
    storage.update_doc(doc_id, status="processing", progress={"step": step, "done": done, "total": total})


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
    d = storage.doc_dir(doc_id)
    key = clean_key(page)
    clean_path = d / "pages" / f"{page['id']}.clean.jpg"
    if page.get("clean_key") == key and clean_path.exists():
        img = read_image(clean_path)
    else:
        img = process_page(read_image(d / page["file"]), page["corners"], page["rotation"], page["filter"])
        write_image(clean_path, img)
        page["clean_key"] = key
    if page.get("ocr_key") != key:
        page["lines"] = page["pdf_lines"] if _uses_pdf_text(page) else ocr.get().ocr(img)
        page["ocr_key"] = key
    return img


def document_text(doc_id: str, max_pages: int = 2) -> str:
    """Reading-order text of the first pages, OCR'ing them if needed (used for AI naming on request)."""
    doc = storage.load_doc(doc_id)
    pages = doc["pages"][:max_pages]
    ocr = _OcrHolder()
    for page in pages:
        prepare_page(doc_id, page, ocr)
    with storage.editing(doc_id) as fresh:  # store the OCR so translating later doesn't redo it
        by_id = {p["id"]: p for p in pages}
        fresh["pages"] = [by_id.get(p["id"], p) for p in fresh["pages"]]
    return page_texts(pages)


def page_texts(pages: list[dict]) -> str:
    return "\n\n".join(b["text"] for i, p in enumerate(pages) for b in group_blocks(p.get("lines") or [], i))


def process(doc_id: str) -> None:
    doc = storage.load_doc(doc_id)
    d = storage.doc_dir(doc_id)
    pages = doc["pages"]
    if not pages:
        raise RuntimeError("Document has no pages")
    n = len(pages)

    # 1. Dewarp + filter, and OCR (both cached per page).
    ocr = _OcrHolder()
    images = []
    for i, page in enumerate(pages):
        _progress(doc_id, "Cleaning and reading pages", i, n)
        images.append(prepare_page(doc_id, page, ocr))
        _save(doc_id, pages=pages)

    blocks_per_page = [group_blocks(p["lines"], i) for i, p in enumerate(pages)]

    # 2. Translate everything not already cached for this model.
    translator = get_translator()
    tcfg = settings.section("translator")
    src, tgt = tcfg.get("source_lang", "German"), tcfg.get("target_lang", "English")
    tkey = translator.cache_key()
    cache = doc.setdefault("tcache", {})

    def ck(text: str) -> str:
        return hashlib.sha1(f"{tkey}|{src}|{tgt}|{text}".encode()).hexdigest()[:20]

    all_blocks = [b for bl in blocks_per_page for b in bl]
    todo = [b for b in all_blocks if ck(b["text"]) not in cache]
    if todo:
        _progress(doc_id, "Translating", 0, 1)
        def on_progress(done: int, total: int) -> None:
            _progress(doc_id, "Translating", done, total)

        for b, t in zip(todo, translator.translate_blocks(todo, src, tgt, on_progress)):
            cache[ck(b["text"])] = t
        _save(doc_id, tcache=cache)

    # 3. Render the three PDFs.
    _progress(doc_id, "Building PDFs", 0, 3)
    render_pages = [
        RenderPage(img, bl, [cache[ck(b["text"])] for b in bl])
        for img, bl in zip(images, blocks_per_page)
    ]
    build_scan_pdf(render_pages, d / OUTPUTS["scan"][0])
    _progress(doc_id, "Building PDFs", 1, 3)
    build_translated_pdf(render_pages, d / OUTPUTS["translated"][0])
    _progress(doc_id, "Building PDFs", 2, 3)
    build_side_by_side_pdf(d / OUTPUTS["scan"][0], d / OUTPUTS["translated"][0], d / OUTPUTS["side_by_side"][0])

    _save(doc_id, pages=pages, tcache=cache, status="done", progress=None, error=None,
          outputs={k: v[0] for k, v in OUTPUTS.items()})


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
