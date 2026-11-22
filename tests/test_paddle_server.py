"""PaddleOCR in its own process (paddle_ocr/server.py), read through the paddle_http engine. Runs only while that
server is up (Settings > Services, engine "PaddleOCR"), since it needs Paddle's own venv and the GPU."""
import httpx
import pytest

from app import services
from app.config import ROOT
from app.ocr.paddle_http import PaddleHttpOcr

URL = "http://localhost:8020/ocr"


def test_the_service_runs_paddle_from_its_own_folder():
    assert services._path("paddle_ocr/.venv/Scripts/python.exe") == ROOT / "paddle_ocr" / ".venv" / "Scripts" / "python.exe"
    assert services._path("~/x").is_absolute()
    assert services._paddle_http_port() == 8020


def test_reads_the_german_letter(letter_image):
    try:
        httpx.get(URL.replace("/ocr", "/health"), timeout=1)
    except httpx.HTTPError:
        pytest.skip("the PaddleOCR server is not running")
    texts = [l["text"] for l in PaddleHttpOcr(URL).ocr(letter_image)]
    assert "Mit freundlichen Grüßen" in texts
    assert any("85,00 EUR erhöht" in t for t in texts)
