"""Extract lines from a digital PDF page's text layer, so no OCR is needed."""
import pymupdf as fitz

from .base import Line


def page_lines(page: fitz.Page, zoom: float) -> list[Line]:
    lines: list[Line] = []
    for block in page.get_text("dict")["blocks"]:
        for ln in block.get("lines", []):
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if not text:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            lines.append({"text": text, "conf": 1.0, "bbox": [x0 * zoom, y0 * zoom, x1 * zoom, y1 * zoom]})
    return lines
