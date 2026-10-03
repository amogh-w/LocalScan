"""Erase OCR'd text lines from a page image while leaving logos, stamps and pictures alone."""
import cv2
import numpy as np

from ..ocr.base import Line


def _pad_box(bbox: list[float], shape: tuple[int, ...], pad: float) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x0, y0, x1, y1 = bbox
    return (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(w, int(x1 + pad + 1)), min(h, int(y1 + pad + 1)))


def text_color(img: np.ndarray, bbox: list[float]) -> tuple[int, int, int]:
    """Estimate the ink colour of a line (RGB 0..255): median of its darkest pixels."""
    x0, y0, x1, y1 = _pad_box(bbox, img.shape, 0)
    crop = img[y0:y1, x0:x1].reshape(-1, 3)
    if crop.size == 0:
        return (0, 0, 0)
    lum = crop.mean(axis=1)
    ink = crop[lum <= np.percentile(lum, 8)]
    b, g, r = np.median(ink, axis=0)
    if max(r, g, b) - min(r, g, b) < 40:  # greyish ink: render as near-black for legibility
        return (20, 20, 20)
    return (int(r), int(g), int(b))


def erase_lines(img: np.ndarray, lines: list[Line]) -> np.ndarray:
    out = img.copy()
    # Erase all lines from the original image's ring samples, so neighbouring lines' ink isn't sampled.
    text_mask = np.zeros(img.shape[:2], bool)
    boxes = []
    for line in lines:
        lh = line["bbox"][3] - line["bbox"][1]
        box = _pad_box(line["bbox"], img.shape, max(2.0, 0.22 * lh))  # room for descenders and accents
        boxes.append((box, lh))
        text_mask[box[1]:box[3], box[0]:box[2]] = True

    for (x0, y0, x1, y1), lh in boxes:
        ring = max(3, int(0.5 * lh))
        rx0, ry0, rx1, ry1 = _pad_box([x0, y0, x1, y1], img.shape, ring)
        region = img[ry0:ry1, rx0:rx1]
        ring_px = region[~text_mask[ry0:ry1, rx0:rx1]]
        if ring_px.size == 0:
            continue
        paper = np.median(ring_px, axis=0)
        near = np.abs(ring_px.astype(int) - paper).max(axis=1) < 30
        if near.mean() > 0.8:
            # Mostly plain paper around the line: fill with its colour (no smudges).
            out[y0:y1, x0:x1] = paper.astype(np.uint8)
        else:
            crop = out[ry0:ry1, rx0:rx1]
            m = np.zeros(crop.shape[:2], np.uint8)
            m[y0 - ry0:y1 - ry0, x0 - rx0:x1 - rx0] = 255
            out[ry0:ry1, rx0:rx1] = cv2.inpaint(crop, m, 3, cv2.INPAINT_TELEA)
    return out
