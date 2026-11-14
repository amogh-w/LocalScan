"""PaddleOCR's own models (PP-OCRv6) run through ONNX Runtime on the CPU, via RapidOCR.

No Paddle, no CUDA, no cuBLAS: this is the engine that keeps working when the GPU libraries crash natively (see
paddle_local.NATIVE_CRASH_HELP). The PP-OCRv6 models are multilingual (German included), so `lang` is not needed.
The model files ship inside the rapidocr wheel, so nothing is downloaded.
"""
import threading
from typing import Any

import numpy as np

from .base import Line
from .paddle_http import parse_response

_lock = threading.Lock()
_model: Any = None


def _load() -> Any:
    global _model
    with _lock:
        if _model is None:
            from rapidocr import RapidOCR

            _model = RapidOCR(params={"Global.log_level": "warning", "Global.use_cls": False})
        return _model


def loaded() -> bool:
    return _model is not None


def preload() -> None:
    _load()


def unload() -> None:
    global _model
    with _lock:
        _model = None


class RapidLocalOcr:
    name = "rapid"

    def __init__(self, lang: str = "", **_: Any) -> None:
        self.lang = lang  # recorded only: the PP-OCRv6 models read every supported language

    def ocr(self, img: np.ndarray) -> list[Line]:
        model = _load()
        with _lock:
            res = model(img)
        if res.boxes is None:
            return []
        return parse_response({"rec_texts": list(res.txts), "rec_scores": [float(s) for s in res.scores],
                               "rec_polys": np.asarray(res.boxes).tolist()})

    def health(self) -> tuple[bool, str]:
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            return False, "RapidOCR is not installed (run: uv sync)"
        return True, "in-process on the CPU" + ("" if loaded() else " (models load on first use)")
