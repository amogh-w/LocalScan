from ..config import settings
from ..languages import ocr_code
from .base import OcrEngine
from .paddle_http import PaddleHttpOcr
from .rapid_local import RapidLocalOcr

ENGINES = {"rapid": RapidLocalOcr, "paddle_http": PaddleHttpOcr}


def get_ocr() -> OcrEngine:
    cfg = settings.section("ocr")
    engine = cfg.get("engine", "rapid")
    if engine not in ENGINES:  # e.g. "paddle_local", the CUDA engine that was removed
        engine = "rapid"
    options = dict(cfg.get(engine, {}))
    if engine == "rapid" and not options.get("lang"):
        options["lang"] = ocr_code()  # an explicit lang in config.toml still wins
    return ENGINES[engine](**options)
