"""PaddleOCR running inside this process on the GPU. Needs: uv sync --extra paddle"""
import os
import subprocess
import sys
import threading
from typing import Any

import numpy as np

from .base import Line
from .paddle_http import parse_response

_lock = threading.Lock()
_models: dict[tuple, Any] = {}
_checked: set[str] = set()

# One 1x1 convolution on the GPU. cuBLAS 12.9 picks its CPU code path from CPUID, so on a PC where Windows has
# AVX-512 switched off while the CPU still advertises it (seen after a Windows update on a Ryzen 9800X3D), the very
# first 1x1 convolution kills the whole process with "illegal instruction". Run in a child process, that crash only
# fails the check instead of taking the server down with it.
_SMOKE = ("import paddle;paddle.set_device({device!r});"
          "paddle.nn.Conv2D(16,16,1)(paddle.randn([1,16,128,128]));paddle.device.cuda.synchronize()")  # size matters: 32x32 passes
NATIVE_CRASH_HELP = (
    "PaddleOCR crashed the GPU libraries at start-up (illegal instruction in cuBLAS). The usual cause is that Windows "
    "has AVX-512 turned off while the CPU still reports it. Check the AVX-512 setting in the BIOS, or turn off "
    "Memory integrity (Windows Security > Device security > Core isolation) and restart, then try again."
)


def check_gpu_libraries(device: str) -> None:
    """Raise a readable error when the GPU libraries die natively, instead of letting them kill this process."""
    if not device.startswith("gpu") or device in _checked:
        return
    done = subprocess.run([sys.executable, "-c", _SMOKE.format(device=device)], capture_output=True, timeout=180)
    if done.returncode != 0:
        raise RuntimeError(f"{NATIVE_CRASH_HELP} (self-test exit code {done.returncode})")
    _checked.add(device)


def _load(lang: str, device: str) -> Any:
    key = (lang, device)
    with _lock:
        if key not in _models:
            # Models already in ~/.paddlex are used as-is; skip the online model-source check.
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            check_gpu_libraries(device)
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
