import hashlib
import io
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

import cv2
import httpx
import pymupdf as fitz
import numpy as np
from PIL import Image
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import imaging, jobs, library, storage
from ..ai import naming, sort
from ..db import blobs
from ..ocr.pdf_text import page_lines
from ..scan.detect import FULL_IMAGE, detect_corners
from ..scan.io import decode_upload, encode_jpeg, read_image
from ..scan.warp import FILTERS, process_page

router = APIRouter(prefix="/api/docs", tags=["documents"])

PDF_IMPORT_DPI = 250


def _doc(doc_id: str) -> dict:
    try:
        return storage.load_doc(doc_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "document not found")


def _page(doc: dict, page_id: str) -> dict:
    try:
        return storage.find_page(doc, page_id)
    except KeyError:
        raise HTTPException(404, "page not found")


@contextmanager
def _edit(doc_id: str) -> Iterator[dict]:
    """Atomic load-change-save of a document (see storage.editing)."""
    _doc(doc_id)  # 404 if missing
    with storage.editing(doc_id) as doc:
        yield doc


def _editable(doc: dict) -> None:
    if doc["status"] in ("queued", "processing"):
        raise HTTPException(409, "document is being processed")


def _mark_dirty(doc: dict) -> None:
    if doc["status"] in ("done", "error"):
        doc["status"] = "draft"


class SortGroup(BaseModel):
    page_ids: list[str] = Field(min_length=1)
    name: str = ""
    name_source: Literal["ai", "manual"] = "manual"


class ApplySort(BaseModel):
    groups: list[SortGroup] = Field(min_length=1, max_length=sort.MAX_PAGES)


class MovePages(BaseModel):
    page_ids: list[str] = Field(min_length=1, max_length=500)
    folder_id: str | None = None  # send it (even null = unfiled) to choose the folder; omit it to keep this document's


class ReturnPages(BaseModel):
    page_ids: list[str] = Field(min_length=1, max_length=500)
    from_doc_id: str
    positions: list[int]


class RemovePages(BaseModel):
    page_ids: list[str] = Field(min_length=1)


class NewDoc(BaseModel):
    name: str = ""


class DocPatch(BaseModel):
    name: str | None = None
    # Who chose the name: "manual" (typed) by default, "ai" when accepting a suggestion.
    name_source: Literal["manual", "ai"] = "manual"
    page_order: list[str] | None = None
    folder_id: str | None = None   # send it (even null = unfiled) to move the document
    tags: list[str] | None = None  # full list of tag ids


class BulkAction(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["move", "tag", "untag", "delete", "restore", "purge"]  # delete = to the trash
    folder_id: str | None = None
    tag_id: str | None = None


class PagePatch(BaseModel):
    corners: list[list[float]] | None = Field(default=None, min_length=4, max_length=4)
    rotation: int | None = None
    filter: str | None = None


@router.get("")
def list_docs(folder: str | None = None, tag: str | None = None, trash: bool = False):
    """folder: a folder id or "none" (unfiled); tag: a tag id; trash: only the trashed documents."""
    return storage.list_docs(folder=folder, tag=tag, trashed=trash)


@router.post("/bulk")
def bulk(body: BulkAction):
    try:
        if body.action == "move":
            library.set_folder(body.ids, body.folder_id)
        elif body.action in ("tag", "untag"):
            if not body.tag_id:
                raise HTTPException(400, "tag_id is required")
            (library.add_tag if body.action == "tag" else library.remove_tag)(body.ids, body.tag_id)
        elif body.action == "restore":
            storage.restore_docs(body.ids)
        elif body.action == "purge":  # for good: only documents that are in the trash, or that a sort just made
            for doc_id in body.ids:
                _editable(_doc(doc_id))
            for doc_id in body.ids:
                storage.delete_doc(doc_id)
        else:
            for doc_id in body.ids:
                _editable(_doc(doc_id))
            storage.trash_doc(body.ids)
    except library.LibraryError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("")
def create_doc(body: NewDoc):
    name = body.name.strip()
    return storage.create_doc(name or time.strftime("Scan %Y-%m-%d %H-%M"), "manual" if name else "default")


@router.get("/{doc_id}")
def get_doc(doc_id: str):
    return _doc(doc_id)


@router.patch("/{doc_id}")
def patch_doc(doc_id: str, body: DocPatch):
    with _edit(doc_id) as doc:
        if body.name is not None and body.name.strip():
            doc["name"] = body.name.strip()[:120]
            doc["name_source"] = body.name_source
        if body.page_order is not None:
            _editable(doc)
            by_id = {p["id"]: p for p in doc["pages"]}
            if sorted(body.page_order) != sorted(by_id):
                raise HTTPException(400, "page_order must list every page once")
            doc["pages"] = [by_id[i] for i in body.page_order]
            _mark_dirty(doc)
    try:
        if "folder_id" in body.model_fields_set:
            library.set_folder([doc_id], body.folder_id)
        if body.tags is not None:
            library.set_tags(doc_id, body.tags)
    except library.LibraryError as e:
        raise HTTPException(400, str(e))
    return _doc(doc_id)


@router.delete("/{doc_id}")
def delete_doc(doc_id: str, permanent: bool = False):
    """Move to the trash; permanent=true deletes for good."""
    doc = _doc(doc_id)
    _editable(doc)
    if permanent:
        storage.delete_doc(doc_id)
    else:
        storage.trash_doc([doc_id])
    return {"ok": True}


@router.post("/trash/empty")
def empty_trash():
    return {"deleted": storage.purge_trash()}


def _original_bytes(data: bytes, img) -> bytes:
    """The uploaded JPEG exactly as received when nothing about it has to change (upright, not resized, plain
    colour); otherwise the decoded pixels, encoded at the re-encode quality."""
    try:
        with Image.open(io.BytesIO(data)) as pil:
            untouched = (pil.format == "JPEG" and pil.mode in ("RGB", "L") and pil.getexif().get(0x0112, 1) == 1
                         and pil.size == (img.shape[1], img.shape[0]))
    except Exception:  # noqa: BLE001 - anything odd is simply re-encoded
        untouched = False
    return data if untouched else encode_jpeg(img, imaging.resize_quality())


def _new_page(doc_id: str, img, source: str = "photo", original_bytes: bytes | None = None) -> dict:
    original = blobs.put(original_bytes or encode_jpeg(img, 94), "jpg")
    h, w = img.shape[:2]
    corners = detect_corners(img) if source == "photo" else [p[:] for p in FULL_IMAGE]
    return {"id": storage.new_id(), "original": original, "width": w, "height": h, "source": source,
            "corners": corners, "detected": corners, "rotation": 0,
            "filter": "enhanced" if source == "photo" else "original"}


@router.post("/{doc_id}/pages")
async def upload_pages(doc_id: str, files: Annotated[list[UploadFile], File()]):
    doc = _doc(doc_id)
    _editable(doc)
    added = []
    for f in files:
        try:
            data = await f.read()
            img = decode_upload(data, imaging.max_edge())
        except Exception:
            raise HTTPException(400, f"{f.filename}: not an image")
        added.append(_new_page(doc_id, img, original_bytes=_original_bytes(data, img)))
    with _edit(doc_id) as doc:  # concurrent uploads from the phone
        doc["pages"].extend(added)
        _mark_dirty(doc)
    return doc


@router.post("/{doc_id}/import-pdf")
async def import_pdf(doc_id: str, file: Annotated[UploadFile, File()]):
    doc = _doc(doc_id)
    _editable(doc)
    try:
        pdf = fitz.open(stream=await file.read(), filetype="pdf")
    except Exception:
        raise HTTPException(400, "not a PDF")
    added = []
    zoom = PDF_IMPORT_DPI / 72
    for pg in pdf:
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3), cv2.COLOR_RGB2BGR)
        page = _new_page(doc_id, img, source="pdf")
        lines = page_lines(pg, zoom)
        if lines:  # digital PDF: use its text layer instead of OCR
            page["pdf_lines"] = lines
        added.append(page)
    with _edit(doc_id) as doc:  # concurrent uploads from the phone
        doc["pages"].extend(added)
        _mark_dirty(doc)
    return doc


@router.patch("/{doc_id}/pages/{page_id}")
def patch_page(doc_id: str, page_id: str, body: PagePatch):
    if body.filter is not None and body.filter not in FILTERS:
        raise HTTPException(400, f"filter must be one of {FILTERS}")
    with _edit(doc_id) as doc:
        _editable(doc)
        page = _page(doc, page_id)
        if body.corners is not None:
            page["corners"] = [[min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))] for x, y in body.corners]
        if body.rotation is not None:
            page["rotation"] = body.rotation % 360
        if body.filter is not None:
            page["filter"] = body.filter
        _mark_dirty(doc)
    return page


@router.delete("/{doc_id}/pages/{page_id}")
def delete_page(doc_id: str, page_id: str):
    with _edit(doc_id) as doc:
        _editable(doc)
        page = _page(doc, page_id)
        storage.trash_pages(doc_id, [page_id])
        doc["pages"].remove(page)
        _mark_dirty(doc)
    storage.collect_garbage()
    return doc


@router.post("/{doc_id}/move-pages")
def move_pages(doc_id: str, body: MovePages):
    """Move pages out of this document into a new scan (in the chosen folder, else this document's)."""
    _editable(_doc(doc_id))
    folder = body.folder_id if "folder_id" in body.model_fields_set else storage.KEEP
    try:
        new, positions = storage.move_pages(doc_id, body.page_ids, folder)
    except KeyError:
        raise HTTPException(400, "a page does not belong to this document")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"document": new, "positions": positions, "source": _doc(doc_id)}


@router.post("/{doc_id}/return-pages")
def return_pages(doc_id: str, body: ReturnPages):
    """Undo move-pages: bring the pages back into this document at their old positions."""
    _editable(_doc(doc_id))
    _editable(_doc(body.from_doc_id))
    try:
        return storage.return_pages(body.from_doc_id, body.page_ids, doc_id, body.positions)
    except KeyError:
        raise HTTPException(400, "a page does not belong to that document")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{doc_id}/remove-pages")
def remove_pages(doc_id: str, body: RemovePages):
    """Remove several pages at once, e.g. the ones just copied into new documents by a sort."""
    with _edit(doc_id) as doc:
        _editable(doc)
        pages = [_page(doc, pid) for pid in dict.fromkeys(body.page_ids)]
        storage.trash_pages(doc_id, [p["id"] for p in pages])
        for page in pages:
            doc["pages"].remove(page)
        _mark_dirty(doc)
    storage.collect_garbage()
    return doc


def _cached_jpeg(key: str, page_id: str, render, headers: dict | None = None) -> Response:
    """Serve a rendered JPEG from the preview cache, rendering and storing it on the first request."""
    key = hashlib.sha1(key.encode()).hexdigest()
    cached = storage.cached_preview(key)
    if cached is not None:
        return FileResponse(cached, media_type="image/jpeg", headers=headers)
    data = render()
    storage.cache_preview(key, page_id, data)
    return Response(data, media_type="image/jpeg", headers=headers)


@router.get("/{doc_id}/pages/{page_id}/image")
def page_image(doc_id: str, page_id: str, size: int = Query(1600, ge=100, le=4000, alias="max")):
    """The original photo, downscaled for the corner editor."""
    page = _page(_doc(doc_id), page_id)

    def render() -> bytes:
        img = read_image(blobs.path(page["original"]))
        h, w = img.shape[:2]
        s = min(1.0, size / max(h, w))
        if s < 1:
            img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        return encode_jpeg(img, 85)

    return _cached_jpeg(f"img|{page['original']}|{size}", page_id, render, {"Cache-Control": "max-age=86400"})


@router.get("/{doc_id}/pages/{page_id}/preview")
def page_preview(doc_id: str, page_id: str, size: int = Query(1200, ge=100, le=3000, alias="max")):
    """The page as it will appear in the PDF (dewarped, rotated, filtered)."""
    page = _page(_doc(doc_id), page_id)

    def render() -> bytes:
        img = read_image(blobs.path(page["original"]))
        return encode_jpeg(process_page(img, page["corners"], page["rotation"], page["filter"], max_long_edge=size), 82)

    key = json.dumps(["pv", jobs.SCAN_VERSION, page["original"], page["corners"], page["rotation"], page["filter"], size])
    return _cached_jpeg(key, page_id, render)


@router.post("/{doc_id}/pages/{page_id}/autodetect")
def autodetect(doc_id: str, page_id: str):
    page = _page(_doc(doc_id), page_id)
    corners = detect_corners(read_image(blobs.path(page["original"])))
    with _edit(doc_id) as doc:
        _editable(doc)
        page = _page(doc, page_id)
        page["corners"] = page["detected"] = corners
        _mark_dirty(doc)
    return page


@router.post("/{doc_id}/sort-pages")
def sort_pages(doc_id: str, split: bool = True):
    """Propose how the pages belong together and in what order. Read-only: nothing is changed.

    split=false only orders the pages (they all belong to one document). Takes a while: every page is read
    and described by the model. Reading the pages stores their OCR, so translating later reuses it.
    """
    doc = _doc(doc_id)
    _editable(doc)  # the worker is using the pages
    if len(doc["pages"]) < 2:
        raise HTTPException(400, "add at least two pages first")
    try:
        return sort.propose(doc_id, split)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama is not reachable: {e}")


@router.get("/{doc_id}/sort-progress")
def sort_progress(doc_id: str):
    """What a running sort-pages call is doing, for the progress bar; {} when none is running."""
    return sort.progress(doc_id) or {}


@router.post("/{doc_id}/apply-sort")
def apply_sort(doc_id: str, body: ApplySort):
    """Create a new document for each group, holding copies of its pages. The original stays as it is."""
    _editable(_doc(doc_id))
    try:
        return {"documents": storage.create_documents_from_pages(doc_id, [g.model_dump() for g in body.groups])}
    except KeyError:
        raise HTTPException(400, "a page does not belong to this document")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{doc_id}/suggest-name")
def suggest_name(doc_id: str):
    """AI name from the text of all pages: {name, date, sender, subject}. Reads pages not yet read first."""
    doc = _doc(doc_id)
    if not doc["pages"]:
        raise HTTPException(400, "add pages first")
    try:
        # While processing, use the text read so far instead of competing with the worker.
        busy = doc["status"] in ("queued", "processing")
        texts = jobs.page_texts(doc["pages"]) if busy else jobs.document_pages_text(doc_id)
        return naming.suggest_name(texts)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama is not reachable: {e}")


@router.post("/{doc_id}/process")
def process_doc(doc_id: str):
    with _edit(doc_id) as doc:
        _editable(doc)
        if not doc["pages"]:
            raise HTTPException(400, "add pages first")
        doc.update(status="queued", progress=None, error=None)
    jobs.enqueue(doc_id)
    return doc


@router.get("/{doc_id}/files/{kind}")
def download(doc_id: str, kind: str, inline: bool = False):
    doc = _doc(doc_id)
    if kind not in jobs.OUTPUTS or kind not in doc.get("outputs", {}):
        raise HTTPException(404, "not generated yet")
    pretty = re.sub(r'[\\/:*?"<>|]', "_", jobs.OUTPUTS[kind].format(name=doc["name"]))
    return FileResponse(blobs.path(doc["outputs"][kind]), media_type="application/pdf", filename=pretty,
                        content_disposition_type="inline" if inline else "attachment")
