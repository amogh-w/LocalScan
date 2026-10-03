"""Image loading helpers that respect EXIF orientation."""
import io

import cv2
import numpy as np
from PIL import Image, ImageOps


def decode_upload(data: bytes, max_long_edge: int = 0) -> np.ndarray:
    """Decode an uploaded photo upright. max_long_edge limits its longest side; 0 keeps every pixel."""
    pil = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if max_long_edge and max(pil.size) > max_long_edge:
        pil.thumbnail((max_long_edge, max_long_edge), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def read_image(path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return img


def write_image(path, img: np.ndarray, quality: int = 92) -> None:
    ext = str(path).rsplit(".", 1)[-1].lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in ("jpg", "jpeg") else []
    ok, buf = cv2.imencode("." + ext, img, params)
    if not ok:
        raise ValueError("encode failed")
    buf.tofile(str(path))


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("encode failed")
    return buf.tobytes()
