"""The languages the app knows, and which two are in use (Settings > Languages).

To support another language, add one entry to LANGUAGES. It then shows up in Settings and applies everywhere:
the OCR model (`ocr`), the translation prompt and cache, and the AI naming prompt all read the chosen pair
from here. `ocr` is the PaddleOCR `lang` code for a language that needs its own model; empty means the
default model, which already reads German and English.
"""
from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Language:
    code: str
    name: str      # English name, used in prompts ("from German to English")
    native: str    # shown in the language's own words
    ocr: str = ""  # PaddleOCR language code; empty = the default models


LANGUAGES: dict[str, Language] = {l.code: l for l in (
    Language("de", "German", "Deutsch"),
    Language("en", "English", "English"),
)}

DEFAULT_SCAN, DEFAULT_TARGET = "de", "en"


def scan_languages() -> list[Language]:
    """The languages the scanned letters may be written in (one or more, in the order of LANGUAGES)."""
    chosen = settings.section("languages").get("scan", DEFAULT_SCAN)
    codes = [chosen] if isinstance(chosen, str) else list(chosen)  # a single code is the older form
    found = [l for c, l in LANGUAGES.items() if c in codes]
    return found or [LANGUAGES[DEFAULT_SCAN]]


def scan_names() -> str:
    """The scan languages as one phrase for prompts: "German", "German and English"."""
    names = [l.name for l in scan_languages()]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 2 else names)


def ocr_code() -> str:
    """PaddleOCR language code. One model reads one language, so with several scan languages the default
    model (which reads German and English) is used; a single language with its own model selects it."""
    chosen = scan_languages()
    return chosen[0].ocr if len(chosen) == 1 else ""


def target_language() -> Language:
    """The language translations and AI names are written in."""
    return LANGUAGES.get(settings.section("languages").get("translate_to", DEFAULT_TARGET), LANGUAGES[DEFAULT_TARGET])
