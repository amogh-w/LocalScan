from fastapi import APIRouter, HTTPException

from .. import services

router = APIRouter(prefix="/api/services", tags=["services"])


def _describe(s: services.Service) -> dict:
    return {"id": s.id, "name": s.name, **s.status()}


def _find(id: str) -> services.Service:
    s = services.get(id)
    if s is None:
        raise HTTPException(404, f"No service {id!r}")
    return s


@router.get("")
def list_services():
    return [_describe(s) for s in services.listing()]


@router.post("/{id}/start")
def start(id: str):
    s = _find(id)
    try:
        s.start()
    except services.ServiceError as e:
        raise HTTPException(400, str(e))
    return _describe(s)


@router.post("/{id}/stop")
def stop(id: str):
    s = _find(id)
    try:
        s.stop()
    except services.ServiceError as e:
        raise HTTPException(400, str(e))
    return _describe(s)


@router.get("/{id}/logs")
def logs(id: str, lines: int = 200):
    return {"text": _find(id).logs(max(1, min(lines, 1000)))}
