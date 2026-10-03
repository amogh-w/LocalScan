from ..config import settings
from .base import Translator
from .ollama import OllamaTranslator

ENGINES = {"ollama": OllamaTranslator}


def get_translator() -> Translator:
    cfg = settings.section("translator")
    engine = cfg.get("engine", "ollama")
    return ENGINES[engine](**cfg.get(engine, {}))
