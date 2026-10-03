"""Photo import without a pixel limit, and the configurable page and PDF quality."""
import io
import itertools

import numpy as np
import pymupdf as fitz
import pytest
from fastapi import HTTPException
from PIL import Image

from app import imaging, jobs
from app.api import documents
from app.api import settings as settings_api
from app.config import settings
from app.render.pdf import RenderPage, build_scan_pdf
from app.scan.io import decode_upload


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    before = dict(settings._overrides)
    settings._overrides = {}
    monkeypatch.setattr(settings, "update", lambda patch: settings._overrides.update({
        k: {**settings._overrides.get(k, {}), **v} if isinstance(v, dict) else v for k, v in patch.items()}))
    monkeypatch.setattr(settings_api.OllamaTranslator, "list_models", lambda self: [])
    yield
    settings._overrides = before


def jpeg(size=(600, 400), exif_orientation=None, mode="RGB") -> bytes:
    rng = np.random.default_rng(1)
    pil = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)).convert(mode)
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        pil.save(buf, "JPEG", exif=exif)
    else:
        pil.save(buf, "JPEG")
    return buf.getvalue()


def test_a_plain_jpeg_is_stored_exactly_as_received():
    data = jpeg()
    assert documents._original_bytes(data, decode_upload(data)) == data  # no limit by default: every pixel stays


def test_a_rotated_jpeg_is_stored_upright_and_other_formats_become_jpeg():
    data = jpeg((600, 400), exif_orientation=6)
    img = decode_upload(data)
    assert img.shape[:2] == (600, 400)  # width and height swapped by the EXIF rotation
    stored = documents._original_bytes(data, img)
    assert stored != data and Image.open(io.BytesIO(stored)).size == (400, 600)
    png = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(png, "PNG")
    assert documents._original_bytes(png.getvalue(), decode_upload(png.getvalue()))[:2] == b"\xff\xd8"


def test_the_size_limit_is_optional():
    data = jpeg((3000, 2000))
    assert max(decode_upload(data, 0).shape[:2]) == 3000
    assert max(decode_upload(data, 2000).shape[:2]) == 2000
    resized = decode_upload(data, 2000)
    assert documents._original_bytes(data, resized) != data  # a resized photo is encoded again


def test_defaults_keep_the_cache_keys_and_a_new_dpi_changes_them():
    page = {"original": "x", "corners": [], "rotation": 0, "filter": "enhanced"}
    default = jobs.clean_key(page)
    settings._overrides["images"] = {"page_dpi": 400}
    assert jobs.clean_key(page) != default
    settings._overrides["images"] = {"page_dpi": 300, "page_quality": 92}
    assert jobs.clean_key(page) == default


def test_presets_and_custom_values():
    assert imaging.pdf_params() == (300, 88) and imaging.page_max_long_edge() == 3508
    settings._overrides["export"] = {"preset": "small"}
    assert imaging.pdf_params() == (200, 75)
    settings._overrides["export"] = {"preset": "custom", "dpi": 450, "quality": 70}
    assert imaging.pdf_params() == (300, 70)  # never above the cleaned page's own resolution
    settings._overrides["images"] = {"page_dpi": 400}
    assert imaging.pdf_params() == (400, 70) and imaging.page_max_long_edge() == 4677


def test_settings_validate_and_round_trip():
    out = settings_api.put_settings(settings_api.SettingsPatch(images={"max_edge": 4000, "page_dpi": 250},
                                                              export={"preset": "archive"}))
    assert out["images"]["max_edge"] == 4000 and out["images"]["page_dpi"] == 250
    assert out["export"]["preset"] == "archive" and out["export"]["effective"] == [250, 92]
    assert out["defaults"]["images"]["max_edge"] == 0 and out["presets"]["small"] == {"dpi": 200, "quality": 75}
    for bad in (dict(images={"max_edge": 100}), dict(images={"page_dpi": 123}), dict(images={"nope": 1}),
                dict(export={"preset": "huge"}), dict(export={"quality": 5}), dict(images={"max_edge": True})):
        with pytest.raises(HTTPException) as e:
            settings_api.put_settings(settings_api.SettingsPatch(**bad))
        assert e.value.status_code == 400
    assert settings_api.upload_config() == {"max_edge": 4000, "resize_quality": 92}


counter = itertools.count()


def pdf_image(tmp_path, img, dpi, quality=88):
    out = tmp_path / f"scan-{next(counter)}.pdf"  # one file per call: Windows cannot overwrite an open PDF
    line = {"text": "Hallo Welt", "conf": 1.0, "bbox": [100, 100, 900, 180]}
    build_scan_pdf([RenderPage(img, [{"text": "Hallo Welt", "bbox": line["bbox"], "lines": [line], "flow": True}], ["x"])],
                   out, dpi, quality, title="A title")
    doc = fitz.open(out)
    xref = doc[0].get_images()[0][0]
    return doc, doc.extract_image(xref)


def test_pdf_images_follow_the_dpi_and_never_upscale(tmp_path):
    rng = np.random.default_rng(2)
    page = rng.integers(200, 255, (3508, 2480, 3), dtype=np.uint8)  # A4 at 300 dpi, colour
    doc, image = pdf_image(tmp_path, page, 150)
    assert abs(image["width"] - 1240) <= 1 and image["ext"] == "jpeg" and image["colorspace"] == 3
    assert "Hallo Welt" in doc[0].get_text() and doc.metadata["title"] == "A title"  # the text layer survives
    small = page[:1000, :700]
    assert pdf_image(tmp_path, small, 300)[1]["width"] == 700  # smaller than the target: left as it is


def test_grey_and_black_and_white_pages_are_stored_compactly(tmp_path):
    rng = np.random.default_rng(3)
    grey = np.repeat(rng.integers(0, 255, (1754, 1240, 1), dtype=np.uint8), 3, axis=2)
    assert pdf_image(tmp_path, grey, 300)[1]["colorspace"] == 1
    bw = np.full((1754, 1240, 3), 255, np.uint8)
    bw[300:310, 100:900] = 0
    assert pdf_image(tmp_path, bw, 300)[1]["ext"] == "png"
