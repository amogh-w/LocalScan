"""PaddleOCR running inside this process on the GPU. Needs: uv sync --extra paddle"""
import os
import threading
from typing import Any

import numpy as np

from .base import Line
from .paddle_http import parse_response

_lock = threading.Lock()
_models: dict[tuple, Any] = {}


def _load(lang: str, device: str) -> Any:
    key = (lang, device)
    with _lock:
        if key not in _models:
            # Models already in ~/.paddlex are used as-is; skip the online model-source check.
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR

            kwargs: dict[str, Any] = dict(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,  # pages are already dewarped by the scan step
                use_textline_orientation=False,
                device=device,
            )
            if lang:
                kwargs["lang"] = lang
            _models[key] = PaddleOCR(**kwargs)
        return _models[key]


def loaded(lang: str, device: str) -> bool:
    return (lang, device) in _models


def preload(lang: str, device: str) -> None:
    """Load the models now instead of on the first page."""
    _load(lang, device)


def unload() -> None:
    """Drop the models and give their GPU memory back. Waits for a page that is being read."""
    with _lock:
        _models.clear()
    import gc

    gc.collect()
    try:
        import paddle

        paddle.device.cuda.empty_cache()
    except Exception:  # noqa: BLE001 - freeing memory is best effort
        pass


class PaddleLocalOcr:
    name = "paddle_local"

    def __init__(self, lang: str = "", device: str = "gpu", **_: Any) -> None:
        self.lang = lang
        self.device = device

    def ocr(self, img: np.ndarray) -> list[Line]:
        model = _load(self.lang, self.device)
        with _lock:  # one GPU predictor, one page at a time
            results = model.predict(img)
        lines: list[Line] = []
        for res in results:
            lines += parse_response({"rec_texts": res.get("rec_texts", []),
                                     "rec_scores": list(res.get("rec_scores", [])),
                                     "rec_polys": [np.asarray(p).tolist() for p in res.get("rec_polys", [])]})
        return lines

    def health(self) -> tuple[bool, str]:
        try:
            import paddle  # noqa: F401 - cheap check that the extra is installed
        except ImportError:
            return False, "PaddleOCR is not installed (run: uv sync --extra paddle)"
        loaded = (self.lang, self.device) in _models
        return True, f"in-process on {self.device}" + ("" if loaded else " (models load on first use)")
