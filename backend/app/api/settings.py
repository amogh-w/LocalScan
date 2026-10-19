import socket

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import imaging
from ..config import settings
from ..languages import LANGUAGES, scan_languages, target_language
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


@router.get("/upload-config")
def upload_config():
    """What the phone needs before it uploads a photo (small, so the document screen can fetch it often)."""
    return {"max_edge": imaging.max_edge(), "resize_quality": imaging.resize_quality()}


DEV_PORT = 5173  # the Vite dev server (hot reload), when it is running


def _listening(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@router.get("/server-info")
def server_info():
    """Where the phone should go: lan_url is the app itself; dev_url is the Vite dev server, only while it runs."""
    port = settings.section("server").get("port", 8000)
    ip = lan_ip()
    return {"lan_url": f"http://{ip}:{port}", "dev_url": f"http://{ip}:{DEV_PORT}" if _listening(DEV_PORT) else None}


class SettingsPatch(BaseModel):
    ocr_engine: str | None = None
    ollama_model: str | None = None
    ollama_url: str | None = None
    paddle_url: str | None = None
    scan_languages: list[str] | None = None
    translate_to: str | None = None
    images: dict[str, int] | None = None
    export: dict[str, int | str] | None = None


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
        "languages": [{"code": l.code, "name": l.name, "native": l.native} for l in LANGUAGES.values()],
        "scan_languages": [l.code for l in scan_languages()],
        "translate_to": target_language().code,
        "images": {k: getattr(imaging, k)() for k in ("max_edge", "resize_quality", "page_dpi", "page_quality")},
        "export": {**imaging._section("export"), "effective": list(imaging.pdf_params())},
        "defaults": imaging.DEFAULTS,
        "presets": {k: {"dpi": v[0], "quality": v[1]} for k, v in imaging.PRESETS.items()},
        "page_dpis": list(imaging.PAGE_DPIS),
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
    if body.scan_languages is not None or body.translate_to is not None:
        scan = body.scan_languages if body.scan_languages is not None else [l.code for l in scan_languages()]
        target = body.translate_to or target_language().code
        for code in [*scan, target]:
            if code not in LANGUAGES:
                raise HTTPException(400, f"unknown language {code!r}")
        if not scan:
            raise HTTPException(400, "Choose at least one scan language")
        if scan == [target]:
            raise HTTPException(400, "There is nothing to translate when the only scan language is the translation language")
        patch["languages"] = {"scan": list(dict.fromkeys(scan)), "translate_to": target}
    if body.images is not None or body.export is not None:
        try:
            checked = imaging.validate({k: v for k, v in (("images", body.images), ("export", body.export)) if v is not None})
        except ValueError as e:
            raise HTTPException(400, str(e))
        for section, values in checked.items():
            patch.setdefault(section, {}).update(values)
    settings.update(patch)
    return get_settings()
