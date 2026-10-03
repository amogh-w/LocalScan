"""Build the scan PDF, the translated PDF and the side-by-side PDF."""
import html
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz

from ..ocr.base import Block
from ..scan.io import encode_jpeg
from .inpaint import erase_lines, text_color

A4 = (595.28, 841.89)


@dataclass
class RenderPage:
    image: np.ndarray            # cleaned page (BGR)
    blocks: list[Block]
    translations: list[str]      # one per block


def page_size(img: np.ndarray) -> tuple[float, float]:
    h, w = img.shape[:2]
    portrait = h >= w
    long_, short = max(h, w), min(h, w)
    if abs(long_ / short - A4[1] / A4[0]) < 0.06:
        return A4 if portrait else (A4[1], A4[0])
    width = A4[0] if portrait else A4[1]
    return width, width * h / w


DEFAULT_DPI, DEFAULT_QUALITY = 300, 88


def pdf_image(img: np.ndarray, pw: float, dpi: int, quality: int) -> tuple[bytes, np.ndarray]:
    """The page image as it goes into the PDF, encoded once: resampled down to `dpi` for a page `pw` points wide
    (never up), then a 1-channel JPEG when the page is grey, or a PNG when it is pure black and white.
    Returns (bytes, the resampled image)."""
    sample = img[::7, ::7]  # what kind of page is it? decided before resampling blurs the levels
    grey = np.array_equal(sample[..., 0], sample[..., 1]) and np.array_equal(sample[..., 1], sample[..., 2])
    black_white = grey and len(np.unique(sample[..., 0])) <= 2
    target = round(pw / 72 * dpi)
    if img.shape[1] > target:
        img = cv2.resize(img, (target, round(img.shape[0] * target / img.shape[1])), interpolation=cv2.INTER_AREA)
    if black_white:
        return cv2.imencode(".png", img[..., 0])[1].tobytes(), img
    if grey:
        return cv2.imencode(".jpg", img[..., 0], [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes(), img
    return encode_jpeg(img, quality), img


def _add_image_page(doc: fitz.Document, img: np.ndarray, dpi: int = DEFAULT_DPI,
                    quality: int = DEFAULT_QUALITY) -> tuple[fitz.Page, float]:
    pw, ph = page_size(img)
    page = doc.new_page(width=pw, height=ph)
    data, _ = pdf_image(img, pw, dpi, quality)
    page.insert_image(page.rect, stream=data)
    return page, pw / img.shape[1]  # zoom is relative to the full image: the text boxes are in its pixels


def _rect(bbox: list[float], zoom: float) -> fitz.Rect:
    return fitz.Rect(bbox[0] * zoom, bbox[1] * zoom, bbox[2] * zoom, bbox[3] * zoom)


def _invisible_text(page: fitz.Page, text: str, rect: fitz.Rect) -> None:
    """Place selectable, invisible text stretched over rect (OCR text layer)."""
    if rect.width <= 1 or rect.height <= 1:
        return
    fs = rect.height * 0.85
    length = fitz.get_text_length(text, fontname="helv", fontsize=fs)
    origin = fitz.Point(rect.x0, rect.y1 - rect.height * 0.2)
    sx = rect.width / length if length else 1.0
    page.insert_text(origin, text, fontname="helv", fontsize=fs, render_mode=3,
                     morph=(origin, fitz.Matrix(sx, 1)))


def build_scan_pdf(pages: list[RenderPage], out: Path, dpi: int = DEFAULT_DPI, quality: int = DEFAULT_QUALITY,
                   title: str = "") -> None:
    doc = fitz.open()
    if title:
        doc.set_metadata({"title": title})
    for p in pages:
        page, zoom = _add_image_page(doc, p.image, dpi, quality)
        for block in p.blocks:
            for line in block["lines"]:
                _invisible_text(page, line["text"], _rect(line["bbox"], zoom))
    doc.save(out, garbage=3, deflate=True)


def line_font_size(line: dict, zoom: float) -> float:
    """Font size in pt, from how wide the OCR'd text is (Helvetica metrics, close to Arial).

    Much steadier than the box height, which changes with ascenders and descenders.
    """
    x0, y0, x1, y1 = line["bbox"]
    h = (y1 - y0) * zoom
    unit = fitz.get_text_length(line["text"].strip(), fontname="helv", fontsize=1)
    by_width = (x1 - x0) * zoom / unit if unit else h
    return float(np.clip(by_width, 0.55 * h, 1.0 * h))


def block_font_size(block: Block, zoom: float) -> float:
    lines = [l for l in block["lines"] if len(l["text"].strip()) >= 4] or block["lines"]
    return float(np.median([line_font_size(l, zoom) for l in lines]))


def snap_sizes(sizes: list[float], tolerance: float = 0.1) -> list[float]:
    """Give blocks of (almost) the same size exactly the same size, as in the original."""
    order = sorted(range(len(sizes)), key=lambda i: sizes[i])
    out = list(sizes)
    group: list[int] = []
    for i in order + [None]:
        if i is not None and (not group or sizes[i] <= sizes[group[0]] * (1 + tolerance)):
            group.append(i)
            continue
        if group:
            m = float(np.median([sizes[j] for j in group]))
            for j in group:
                out[j] = m
        group = [i] if i is not None else []
    return out


def _css(font_size: float, line_height: float, color: tuple[int, int, int]) -> str:
    r, g, b = color
    return (f"* {{font-family: sans-serif; font-size: {font_size:.2f}pt; line-height: {line_height:.3f}; "
            f"color: rgb({r},{g},{b}); margin: 0; padding: 0;}}")


def _fit(page: fitz.Page, own: fitz.Rect, wide: fitz.Rect, body: str, css: str) -> None:
    """Place text at full size in its own box, else in the free space around it, shrinking only last."""
    for rect, scale_low in ((own, 1), (wide, 1), (wide, 0.8), (wide, 0)):
        spare, _ = page.insert_htmlbox(rect, body, css=css, scale_low=scale_low)
        if spare >= 0:
            return


def obstacle_mask(img: np.ndarray, blocks: list[Block], zoom: float) -> np.ndarray:
    """Non-text ink (logos, stamps, signatures, rules) at 1 px = 1 pt, which text must not grow over."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, round(w * zoom)), max(1, round(h * zoom))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    ink = gray < 200
    for b in blocks:
        for l in b["lines"]:
            x0, y0, x1, y1 = (v * zoom for v in l["bbox"])
            pad = (y1 - y0) * 0.3
            ink[max(0, int(y0 - pad)):int(y1 + pad) + 1, max(0, int(x0 - pad)):int(x1 + pad) + 1] = False
    # Ignore specks; keep anything the size of a logo stroke or bigger.
    ink = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)).astype(bool)
    # Shadows or table left at the page edge are not content.
    m = max(2, round(0.015 * min(ink.shape)))
    ink[:m, :] = ink[-m:, :] = False
    ink[:, :m] = ink[:, -m:] = False
    return ink


def grow_boxes(boxes: list[list[float]], page_w: float, page_h: float,
               obstacles: np.ndarray | None = None) -> list[list[float]]:
    """Let each box grow right and down into free space, so longer translations need less shrinking.

    A box grows right up to the nearest box beside it, an obstacle (logo, stamp), or the right text margin
    of the page. It grows down by at most one line height, never into the box or obstacle below.
    """
    if not boxes:
        return []
    right_margin = max(max(b[2] for b in boxes), page_w * 0.88)
    grown = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        lh = y1 - y0
        gap = max(3.0, lh * 0.3)
        max_x1 = right_margin
        max_y1 = min(page_h - 2, y1 + lh)
        for j, (a0, b0, a1, b1) in enumerate(boxes):
            if i == j:
                continue
            if b0 < y1 and b1 > y0 and a0 >= x1 - 1:  # beside, to the right
                max_x1 = min(max_x1, a0 - gap)
        if obstacles is not None:
            band = obstacles[int(y0):int(y1) + 1, int(x1):int(max_x1)]
            cols = np.flatnonzero(band.any(axis=0)) if band.size else []
            if len(cols):
                max_x1 = min(max_x1, x1 + cols[0] - gap)
        for j, (a0, b0, a1, b1) in enumerate(boxes):
            if i != j and a0 < max_x1 and a1 > x0 and b0 >= y1 - 1:  # below, in the widened span
                max_y1 = min(max_y1, b0 - 1)
        if obstacles is not None:
            band = obstacles[int(y1):int(max_y1) + 1, int(x0):int(max(x1, max_x1))]
            rows = np.flatnonzero(band.any(axis=1)) if band.size else []
            if len(rows):
                max_y1 = min(max_y1, y1 + rows[0] - 1)
        grown.append([x0, y0, max(x1, max_x1), max(y1, max_y1)])
    return grown


def build_translated_pdf(pages: list[RenderPage], out: Path, dpi: int = DEFAULT_DPI, quality: int = DEFAULT_QUALITY,
                         title: str = "") -> None:
    doc = fitz.open()
    if title:
        doc.set_metadata({"title": title})
    for p in pages:
        lines = [line for block in p.blocks for line in block["lines"]]
        page, zoom = _add_image_page(doc, erase_lines(p.image, lines), dpi, quality)
        boxes = grow_boxes([[v * zoom for v in b["bbox"]] for b in p.blocks], page.rect.width, page.rect.height,
                           obstacle_mask(p.image, p.blocks, zoom))
        sizes = snap_sizes([block_font_size(b, zoom) for b in p.blocks])
        for block, text, box, fs in zip(p.blocks, p.translations, boxes, sizes):
            color = text_color(p.image, block["lines"][0]["bbox"])
            src_lines = block["lines"]
            out_lines = text.split("\n")

            if not block.get("flow", True) and len(out_lines) == len(src_lines):
                # Address, table or list: each translated line goes where its source line was.
                for line, t in zip(src_lines, out_lines):
                    r = _rect(line["bbox"], zoom)
                    own = fitz.Rect(r.x0, r.y0, r.x1 + 2, r.y1 + r.height * 0.3)
                    wide = fitz.Rect(r.x0, r.y0, max(own.x1, box[2]), own.y1)
                    _fit(page, own, wide, html.escape(t.strip()), _css(fs, 1.15, color))
                continue

            n = len(src_lines)
            if n > 1:  # keep the source's line spacing
                pitch = (src_lines[-1]["bbox"][1] - src_lines[0]["bbox"][1]) * zoom / (n - 1)
                line_height = float(np.clip(pitch / fs, 1.0, 1.8))
            else:
                line_height = 1.15
            body = "<br>".join(html.escape(t.strip()) for t in out_lines)
            own = _rect(block["bbox"], zoom)
            # A little slack: Helvetica runs slightly wider than many letter fonts.
            own = fitz.Rect(own.x0, own.y0, min(own.x1 + own.width * 0.04 + 2, max(own.x1 + 2, box[2])),
                            own.y1 + own.height / n * 0.5)
            _fit(page, own, fitz.Rect(box), body, _css(fs, line_height, color))
    # Every insert_htmlbox call embeds its own whole font, about 35 KB per text box (145 fonts, 5 MB for a
    # 3-page letter). Subsetting merges them into one small font per face (0.4 MB), with identical text.
    doc.subset_fonts()
    doc.save(out, garbage=4, deflate=True, deflate_fonts=True)


def build_side_by_side_pdf(scan_pdf: Path, translated_pdf: Path, out: Path, gap: float = 18) -> None:
    left, right = fitz.open(scan_pdf), fitz.open(translated_pdf)
    doc = fitz.open()
    for i in range(len(left)):
        lr, rr = left[i].rect, right[i].rect
        page = doc.new_page(width=lr.width + gap + rr.width, height=max(lr.height, rr.height))
        page.show_pdf_page(fitz.Rect(0, 0, lr.width, lr.height), left, i)
        page.show_pdf_page(fitz.Rect(lr.width + gap, 0, lr.width + gap + rr.width, rr.height), right, i)
        page.draw_line(fitz.Point(lr.width + gap / 2, 0), fitz.Point(lr.width + gap / 2, page.rect.height),
                       color=(0.8, 0.8, 0.8), width=0.5)
    doc.save(out, garbage=4, deflate=True, deflate_fonts=True)
