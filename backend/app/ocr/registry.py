from ..config import settings
from ..languages import ocr_code
from .base import OcrEngine
from .paddle_http import PaddleHttpOcr
from .paddle_local import PaddleLocalOcr

ENGINES = {"paddle_local": PaddleLocalOcr, "paddle_http": PaddleHttpOcr}


def get_ocr() -> OcrEngine:
    cfg = settings.section("ocr")
    engine = cfg.get("engine", "paddle_local")
    options = dict(cfg.get(engine, {}))
    if engine == "paddle_local" and not options.get("lang"):
        options["lang"] = ocr_code()  # an explicit lang in config.toml still wins
    return ENGINES[engine](**options)
