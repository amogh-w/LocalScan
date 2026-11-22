"""PaddleOCR on the GPU as a small HTTP server, in its own venv (this folder), so Paddle and its CUDA libraries never
mix with Local Scan's packages and a native crash here cannot take the app down.

Local Scan starts it from Settings > Services (engine "paddle_http"). By hand:
    .venv\\Scripts\\python -m uvicorn server:app --port 8020

POST /ocr with a multipart "file" (an image) returns {"results": [{"text", "confidence", "box"}]}, the format
Local Scan's paddle_http engine reads with request = "multipart".
"""
import os
import threading

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")  # use the models in ~/.paddlex as they are

DEVICE = os.environ.get("PADDLE_OCR_DEVICE", "gpu")
LANG = os.environ.get("PADDLE_OCR_LANG", "")  # empty = PaddleOCR's default (multilingual PP-OCRv6) models

app = FastAPI(title="Local Scan PaddleOCR")
_lock = threading.Lock()
_model = None


def model():
    global _model
    with _lock:
        if _model is None:
            from paddleocr import PaddleOCR

            kwargs = dict(use_doc_orientation_classify=False, use_doc_unwarping=False,  # pages arrive dewarped
                          use_textline_orientation=False, device=DEVICE)
            if LANG:
                kwargs["lang"] = LANG
            _model = PaddleOCR(**kwargs)
        return _model


@app.on_event("startup")
def load() -> None:
    model()  # load now, so "running" in Settings means ready


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "device": DEVICE}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)) -> dict:
    img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode the image")
    m = model()
    with _lock:  # one GPU predictor, one page at a time
        results = m.predict(img)
    return {"results": [{"text": t, "confidence": float(s), "box": np.asarray(p).tolist()}
                        for r in results for t, s, p in zip(r.get("rec_texts", []), r.get("rec_scores", []),
                                                           r.get("rec_polys", []))]}
