import socket

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..ocr.registry import ENGINES as OCR_ENGINES, get_ocr
from ..translate.ollama import OllamaTranslator
from ..translate.registry import get_translator

router = APIRouter(prefix="/api", tags=["settings"])


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@router.get("/health")
def health():
    ocr_ok, ocr_msg = get_ocr().health()
    tr_ok, tr_msg = get_translator().health()
    return {"ocr": {"ok": ocr_ok, "detail": ocr_msg}, "translator": {"ok": tr_ok, "detail": tr_msg}}


@router.get("/server-info")
def server_info():
    port = settings.section("server").get("port", 8000)
    return {"lan_url": f"http://{lan_ip()}:{port}"}


class SettingsPatch(BaseModel):
    ocr_engine: str | None = None
    ollama_model: str | None = None
    ollama_url: str | None = None
    paddle_url: str | None = None


@router.get("/settings")
def get_settings():
    v = settings.values
    models: list[str] = []
    error = None
    if v["translator"]["engine"] == "ollama":
        try:
            models = OllamaTranslator(**v["translator"]["ollama"]).list_models()
        except Exception as e:  # noqa: BLE001 - shown in the UI
            error = str(e)
    return {
        "translator": v["translator"]["engine"],
        "ollama_url": v["translator"]["ollama"]["url"],
        "ollama_model": v["translator"]["ollama"].get("model", ""),
        "ollama_models": models,
        "ollama_error": error,
        "ocr": v["ocr"]["engine"],
        "ocr_engines": list(OCR_ENGINES),
        "paddle_url": v["ocr"]["paddle_http"]["url"],
    }


@router.put("/settings")
def put_settings(body: SettingsPatch):
    patch: dict = {}
    if body.ollama_model is not None or body.ollama_url is not None:
        o = {}
        if body.ollama_model is not None:
            o["model"] = body.ollama_model
        if body.ollama_url is not None:
            if not body.ollama_url.startswith("http"):
                raise HTTPException(400, "URL must start with http")
            o["url"] = body.ollama_url
        patch["translator"] = {"ollama": o}
    if body.ocr_engine is not None:
        if body.ocr_engine not in OCR_ENGINES:
            raise HTTPException(400, f"OCR engine must be one of {list(OCR_ENGINES)}")
        patch.setdefault("ocr", {})["engine"] = body.ocr_engine
    if body.paddle_url is not None:
        if not body.paddle_url.startswith("http"):
            raise HTTPException(400, "URL must start with http")
        patch.setdefault("ocr", {})["paddle_http"] = {"url": body.paddle_url}
    settings.update(patch)
    return get_settings()
