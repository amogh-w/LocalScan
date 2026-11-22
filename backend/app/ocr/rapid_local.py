"""PaddleOCR's own models (PP-OCRv6) run through ONNX Runtime, via RapidOCR: on the GPU with DirectML, or on the CPU.

No Paddle, no CUDA, no cuBLAS: CUDA's cuBLAS crashes natively on this PC while Windows has AVX-512 switched off
(Memory integrity on), and it took the whole server down with it. DirectML goes through DirectX 12 instead. The PP-OCRv6 models are multilingual (German included), so `lang` is not needed.
The model files ship inside the rapidocr wheel, so nothing is downloaded.
"""
import threading
from typing import Any

import numpy as np

from .base import Line
from .paddle_http import parse_response

_lock = threading.Lock()
_model: Any = None
_device = ""  # what the loaded model runs on, for the status line


def _load(device: str = "gpu") -> Any:
    global _model, _device
    with _lock:
        if _model is None:
            import onnxruntime as ort
            from rapidocr import RapidOCR

            dml = device == "gpu" and "DmlExecutionProvider" in ort.get_available_providers()
            _model = RapidOCR(params={"Global.log_level": "warning", "Global.use_cls": False,
                                      "EngineConfig.onnxruntime.use_dml": dml})
            _device = "the GPU (DirectML)" if dml else "the CPU"
        return _model


def loaded() -> bool:
    return _model is not None


def device() -> str:
    return _device


def preload(device: str = "gpu") -> None:
    _load(device)


def unload() -> None:
    global _model
    with _lock:
        _model = None


class RapidLocalOcr:
    name = "rapid"

    def __init__(self, lang: str = "", device: str = "gpu", **_: Any) -> None:
        self.device = device  # "gpu" = DirectML when available, else the CPU; "cpu" forces the CPU
        self.lang = lang  # recorded only: the PP-OCRv6 models read every supported language

    def ocr(self, img: np.ndarray) -> list[Line]:
        model = _load(self.device)
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
        return True, (f"in-process on {_device}" if loaded() else "in-process (models load on first use)")
