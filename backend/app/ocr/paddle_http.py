"""Client for a PaddleOCR HTTP endpoint (PaddleX serving or PaddleHub serving)."""
import base64
from typing import Any

import httpx
import numpy as np

from ..scan.io import encode_jpeg
from .base import Line


def _poly_to_bbox(poly: Any) -> list[float]:
    pts = np.asarray(poly, dtype=float).reshape(-1, 2)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())]


def _is_raw_item(it: Any) -> bool:
    """A raw paddleocr.ocr() item looks like [poly, (text, score)]."""
    return isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[1], (list, tuple)) \
        and len(it[1]) == 2 and isinstance(it[1][0], str)


def parse_response(payload: Any) -> list[Line]:
    """Accept the common PaddleOCR response shapes and normalise them to Lines."""
    lines: list[Line] = []

    def add(text: str, conf: float, poly: Any) -> None:
        text = (text or "").strip()
        if text:
            lines.append({"text": text, "conf": float(conf), "bbox": _poly_to_bbox(poly)})

    if isinstance(payload, dict):
        if payload.get("errorCode") not in (None, 0):
            raise RuntimeError(f"PaddleOCR error {payload.get('errorCode')}: {payload.get('errorMsg')}")
        result = payload.get("result", payload)
        if isinstance(result, dict) and "rec_texts" in result:
            result = {"ocrResults": [result]}
        # PaddleX serving: result.ocrResults[].prunedResult.{rec_texts, rec_scores, rec_polys|rec_boxes}
        if isinstance(result, dict) and "ocrResults" in result:
            for r in result["ocrResults"]:
                pr = r.get("prunedResult", r)
                polys = pr.get("rec_polys") or pr.get("dt_polys") or pr.get("rec_boxes") or []
                scores = pr.get("rec_scores") or [1.0] * len(pr.get("rec_texts", []))
                for text, score, poly in zip(pr.get("rec_texts", []), scores, polys):
                    if np.asarray(poly).size == 4:  # rec_boxes: x0, y0, x1, y1
                        x0, y0, x1, y1 = np.asarray(poly, dtype=float).ravel()
                        poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                    add(text, score, poly)
            return lines
        # PaddleHub serving: results[0] = [{text, confidence, text_region}]
        # Simple custom servers:   results = [{text, confidence, box}]
        if "results" in payload:
            results = payload["results"]
            items = results[0] if results and isinstance(results[0], list) else results
            for it in items:
                poly = it.get("box") or it.get("text_region") or it.get("poly") or it.get("bbox")
                if poly is not None and np.asarray(poly).size == 4:
                    x0, y0, x1, y1 = np.asarray(poly, dtype=float).ravel()
                    poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                add(it.get("text", ""), it.get("confidence", it.get("score", 1.0)), poly)
            return lines
    # Raw paddleocr.ocr() output, optionally wrapped in a per-page list.
    if isinstance(payload, list):
        items = payload
        if payload and isinstance(payload[0], list) and payload[0] and _is_raw_item(payload[0][0]):
            items = payload[0]
        for it in items:
            if _is_raw_item(it):
                add(it[1][0], it[1][1], it[0])
        return lines
    raise RuntimeError("Unrecognised PaddleOCR response format")


class PaddleHttpOcr:
    name = "paddle_http"

    def __init__(self, url: str, timeout: float = 120, request: str = "multipart", **_: Any) -> None:
        self.url = url
        self.timeout = timeout
        self.request = request  # "multipart" (file upload), "paddlex" or "paddlehub" (base64 JSON)

    def ocr(self, img: np.ndarray) -> list[Line]:
        jpeg = encode_jpeg(img, 95)
        if self.request == "multipart":
            r = httpx.post(self.url, files={"file": ("page.jpg", jpeg, "image/jpeg")}, timeout=self.timeout)
        else:
            b64 = base64.b64encode(jpeg).decode()
            body = {"images": [b64]} if self.request == "paddlehub" else {
                "file": b64, "fileType": 1, "visualize": False,
                "useDocOrientationClassify": False, "useDocUnwarping": False}
            r = httpx.post(self.url, json=body, timeout=self.timeout)
        r.raise_for_status()
        return parse_response(r.json())

    def health(self) -> tuple[bool, str]:
        try:
            self.ocr(np.full((64, 256, 3), 255, np.uint8))
            return True, self.url
        except Exception as e:  # noqa: BLE001 - shown in the UI
            return False, f"{self.url}: {e}"
