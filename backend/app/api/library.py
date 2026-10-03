from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import library

router = APIRouter(prefix="/api", tags=["library"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "not found")
    except library.LibraryError as e:
        raise HTTPException(400, str(e))


class FolderIn(BaseModel):
    name: str
    parent_id: str | None = None


class FolderPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None  # send it (even null) to move the folder


class TagIn(BaseModel):
    name: str
    color: str | None = None


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None


@router.get("/folders")
def list_folders():
    return library.list_folders()


@router.post("/folders")
def create_folder(body: FolderIn):
    return _call(library.create_folder, body.name, body.parent_id)


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: str, body: FolderPatch):
    return _call(library.update_folder, folder_id, name=body.name, parent_id=body.parent_id,
                 move="parent_id" in body.model_fields_set)


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str):
    _call(library.delete_folder, folder_id)
    return {"ok": True}


@router.get("/tags")
def list_tags():
    return {"tags": library.list_tags(), "colors": list(library.TAG_COLORS)}


@router.post("/tags")
def create_tag(body: TagIn):
    return _call(library.create_tag, body.name, body.color)


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: str, body: TagPatch):
    return _call(library.update_tag, tag_id, name=body.name, color=body.color)


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: str):
    _call(library.delete_tag, tag_id)
    return {"ok": True}
