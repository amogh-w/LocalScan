from ..config import settings
from .base import OcrEngine
from .paddle_http import PaddleHttpOcr
from .paddle_local import PaddleLocalOcr

ENGINES = {"paddle_local": PaddleLocalOcr, "paddle_http": PaddleHttpOcr}


def get_ocr() -> OcrEngine:
    cfg = settings.section("ocr")
    engine = cfg.get("engine", "paddle_local")
    return ENGINES[engine](**cfg.get(engine, {}))
