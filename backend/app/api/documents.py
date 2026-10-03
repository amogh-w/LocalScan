import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import cv2
import pymupdf as fitz
import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import jobs, storage
from ..ocr.pdf_text import page_lines
from ..scan.detect import FULL_IMAGE, detect_corners
from ..scan.io import decode_upload, encode_jpeg, read_image, write_image
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


class NewDoc(BaseModel):
    name: str = ""


class DocPatch(BaseModel):
    name: str | None = None
    page_order: list[str] | None = None


class PagePatch(BaseModel):
    corners: list[list[float]] | None = Field(default=None, min_length=4, max_length=4)
    rotation: int | None = None
    filter: str | None = None


@router.get("")
def list_docs():
    return storage.list_docs()


@router.post("")
def create_doc(body: NewDoc):
    name = body.name.strip() or time.strftime("Scan %Y-%m-%d %H-%M")
    return storage.create_doc(name)


@router.get("/{doc_id}")
def get_doc(doc_id: str):
    return _doc(doc_id)


@router.patch("/{doc_id}")
def patch_doc(doc_id: str, body: DocPatch):
    with _edit(doc_id) as doc:
        if body.name is not None:
            doc["name"] = body.name.strip() or doc["name"]
        if body.page_order is not None:
            _editable(doc)
            by_id = {p["id"]: p for p in doc["pages"]}
            if sorted(body.page_order) != sorted(by_id):
                raise HTTPException(400, "page_order must list every page once")
            doc["pages"] = [by_id[i] for i in body.page_order]
            _mark_dirty(doc)
    return doc


@router.delete("/{doc_id}")
def delete_doc(doc_id: str):
    doc = _doc(doc_id)
    _editable(doc)
    shutil.rmtree(storage.doc_dir(doc_id), ignore_errors=True)
    return {"ok": True}


def _new_page(doc_id: str, img, source: str = "photo") -> dict:
    page_id = storage.new_id()
    rel = f"pages/{page_id}.jpg"
    write_image(storage.doc_dir(doc_id) / rel, img, 94)
    h, w = img.shape[:2]
    corners = detect_corners(img) if source == "photo" else [p[:] for p in FULL_IMAGE]
    return {"id": page_id, "file": rel, "width": w, "height": h, "source": source,
            "corners": corners, "detected": corners, "rotation": 0,
            "filter": "enhanced" if source == "photo" else "original"}


@router.post("/{doc_id}/pages")
async def upload_pages(doc_id: str, files: Annotated[list[UploadFile], File()]):
    doc = _doc(doc_id)
    _editable(doc)
    added = []
    for f in files:
        try:
            img = decode_upload(await f.read())
        except Exception:
            raise HTTPException(400, f"{f.filename}: not an image")
        added.append(_new_page(doc_id, img))
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
        doc["pages"].remove(_page(doc, page_id))
        _mark_dirty(doc)
    for p in storage.doc_dir(doc_id).joinpath("pages").glob(f"{page_id}.*"):
        p.unlink(missing_ok=True)
    return doc


@router.get("/{doc_id}/pages/{page_id}/image")
def page_image(doc_id: str, page_id: str, size: int = Query(1600, ge=100, le=4000, alias="max")):
    """The original photo, downscaled for the corner editor."""
    page = _page(_doc(doc_id), page_id)
    img = read_image(storage.doc_dir(doc_id) / page["file"])
    h, w = img.shape[:2]
    s = min(1.0, size / max(h, w))
    if s < 1:
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return Response(encode_jpeg(img, 85), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.get("/{doc_id}/pages/{page_id}/preview")
def page_preview(doc_id: str, page_id: str, size: int = Query(1200, ge=100, le=3000, alias="max")):
    """The page as it will appear in the PDF (dewarped, rotated, filtered)."""
    page = _page(_doc(doc_id), page_id)
    img = read_image(storage.doc_dir(doc_id) / page["file"])
    out = process_page(img, page["corners"], page["rotation"], page["filter"], max_long_edge=size)
    return Response(encode_jpeg(out, 82), media_type="image/jpeg")


@router.post("/{doc_id}/pages/{page_id}/autodetect")
def autodetect(doc_id: str, page_id: str):
    page = _page(_doc(doc_id), page_id)
    corners = detect_corners(read_image(storage.doc_dir(doc_id) / page["file"]))
    with _edit(doc_id) as doc:
        _editable(doc)
        page = _page(doc, page_id)
        page["corners"] = page["detected"] = corners
        _mark_dirty(doc)
    return page


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
    fname, pretty = jobs.OUTPUTS[kind]
    pretty = re.sub(r'[\\/:*?"<>|]', "_", pretty.format(name=doc["name"]))
    return FileResponse(storage.doc_dir(doc_id) / fname, media_type="application/pdf", filename=pretty,
                        content_disposition_type="inline" if inline else "attachment")
