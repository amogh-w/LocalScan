"""The RapidOCR engine (PaddleOCR's models on ONNX Runtime), its Settings service, and how the built app is cached."""
import time

import pytest
from fastapi.testclient import TestClient

from app import services
from app.ocr import rapid_local
from app.ocr.registry import get_ocr

pytest.importorskip("rapidocr")


@pytest.fixture
def fresh_model():
    rapid_local.unload()
    yield
    rapid_local.unload()


def test_reads_the_german_letter_on_the_cpu(letter_image, fresh_model):
    lines = rapid_local.RapidLocalOcr(device="cpu").ocr(letter_image)
    texts = [l["text"] for l in lines]
    assert "Mit freundlichen Grüßen" in texts  # umlauts and ß survive
    assert any("85,00 EUR erhöht" in t for t in texts)
    assert rapid_local.device() == "the CPU"
    x0, y0, x1, y1 = next(l["bbox"] for l in lines if l["text"] == "Mit freundlichen Grüßen")
    assert x0 < x1 and y0 < y1 and all(0.5 < l["conf"] <= 1 for l in lines)


def test_is_the_default_engine_and_gets_the_scan_language():
    ocr = get_ocr()
    assert ocr.name == "rapid" and ocr.lang is not None
    assert ocr.health()[0]


def test_settings_service_loads_and_frees_the_models(monkeypatch, fresh_model):
    monkeypatch.setattr(rapid_local, "_load", lambda device="gpu": setattr(rapid_local, "_model", object()))  # no real models
    svc = services.LocalRapid()
    assert svc.status()["state"] == "stopped"
    svc.start()
    end = time.time() + 5
    while svc.status()["state"] != "running" and time.time() < end:
        time.sleep(0.05)
    assert svc.status()["state"] == "running"
    svc.stop()
    assert svc.status()["state"] == "stopped" and not rapid_local.loaded()


def test_a_load_error_is_shown_not_raised(monkeypatch, fresh_model):
    def broken(device="gpu"):
        raise RuntimeError("no models")

    monkeypatch.setattr(rapid_local, "preload", broken)
    svc = services.LocalRapid()
    svc.start()
    svc._thread.join(5)
    assert svc.status() == {"state": "stopped", "detail": "loading failed: no models"}


def test_the_built_page_is_never_cached_stale():
    from app.main import DIST, app

    if not (DIST / "index.html").exists():
        pytest.skip("frontend not built")
    r = TestClient(app).get("/")  # no `with`: the startup (real database, worker) does not run
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
