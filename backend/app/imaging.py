"""Image and PDF quality settings (Settings > Photos & PDFs), with their defaults and limits.

Photos: `max_edge` limits the longest side of an uploaded photo (0 = keep every pixel). The cleaned page is
warped to `page_dpi` (A4 long edge = dpi x 11.69 in) and stored at `page_quality`. The PDFs use a preset (or
custom values) and never exceed the cleaned page's resolution, so nothing is upscaled.
"""
from typing import Any

from .config import settings

A4_LONG_MM = 297
DEFAULTS: dict[str, dict[str, Any]] = {
    "images": {"max_edge": 0, "resize_quality": 92, "page_dpi": 300, "page_quality": 92},
    "export": {"preset": "standard", "dpi": 300, "quality": 88},
}
PRESETS = {"archive": (300, 92), "standard": (300, 88), "small": (200, 75)}  # (dpi, JPEG quality)
PAGE_DPIS = (200, 250, 300, 400)
LIMITS = {  # (min, max) of the numbers the user can set
    "max_edge": (2000, 8000), "resize_quality": (50, 100), "page_quality": (50, 100), "dpi": (100, 600), "quality": (40, 100),
}


def _section(name: str) -> dict[str, Any]:
    return {**DEFAULTS[name], **settings.section(name)}


def max_edge() -> int:
    """Longest side an uploaded photo may keep, in px. 0 means no limit."""
    return int(_section("images")["max_edge"])


def resize_quality() -> int:
    return int(_section("images")["resize_quality"])


def page_dpi() -> int:
    return int(_section("images")["page_dpi"])


def page_quality() -> int:
    return int(_section("images")["page_quality"])


def page_max_long_edge() -> int:
    """Pixels on the long side of the cleaned page (3508 at 300 dpi)."""
    return round(page_dpi() * A4_LONG_MM / 25.4)


def pdf_params() -> tuple[int, int]:
    """(dpi, JPEG quality) for the PDF page images. The dpi never exceeds the cleaned page's."""
    cfg = _section("export")
    dpi, quality = PRESETS.get(cfg["preset"], (int(cfg["dpi"]), int(cfg["quality"])))
    return min(dpi, page_dpi()), quality


def uses_default_pages() -> bool:
    d = DEFAULTS["images"]
    return page_dpi() == d["page_dpi"] and page_quality() == d["page_quality"]


def validate(patch: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Check a partial update of the images / export sections; returns it cleaned. Raises ValueError."""
    out: dict[str, dict[str, Any]] = {}
    for section, values in patch.items():
        if section not in DEFAULTS:
            raise ValueError(f"unknown section {section!r}")
        clean = out.setdefault(section, {})
        for key, value in values.items():
            if key not in DEFAULTS[section]:
                raise ValueError(f"unknown setting {section}.{key}")
            if key == "preset":
                if value not in (*PRESETS, "custom"):
                    raise ValueError(f"preset must be one of {[*PRESETS, 'custom']}")
            elif isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a whole number")
            elif key == "max_edge" and value == 0:
                pass  # no limit
            elif key == "page_dpi":
                if value not in PAGE_DPIS:
                    raise ValueError(f"page_dpi must be one of {list(PAGE_DPIS)}")
            elif not LIMITS[key][0] <= value <= LIMITS[key][1]:
                raise ValueError(f"{key} must be between {LIMITS[key][0]} and {LIMITS[key][1]}")
            clean[key] = value
    return out
