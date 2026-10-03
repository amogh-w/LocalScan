"""Documents live in data/docs/<doc_id>/ with a doc.json manifest and page images."""
import json
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings

DOCS_DIR = settings.data_dir / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def doc_dir(doc_id: str) -> Path:
    if not doc_id.isalnum():
        raise ValueError("bad doc id")
    return DOCS_DIR / doc_id


def create_doc(name: str) -> dict[str, Any]:
    doc_id = new_id()
    d = doc_dir(doc_id)
    (d / "pages").mkdir(parents=True)
    doc = {
        "id": doc_id,
        "name": name,
        "created": time.time(),
        "pages": [],
        "status": "draft",  # draft | queued | processing | done | error
        "progress": None,
        "error": None,
        "outputs": {},
    }
    save_doc(doc)
    return doc


def load_doc(doc_id: str) -> dict[str, Any]:
    p = doc_dir(doc_id) / "doc.json"
    if not p.exists():
        raise KeyError(doc_id)
    with _lock:
        return json.loads(p.read_text("utf-8"))


def save_doc(doc: dict[str, Any]) -> None:
    p = doc_dir(doc["id"]) / "doc.json"
    with _lock:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(p)


@contextmanager
def editing(doc_id: str) -> Iterator[dict[str, Any]]:
    """Load, change and save a document as one step, so concurrent edits can't overwrite each other."""
    with _lock:
        doc = load_doc(doc_id)
        yield doc
        save_doc(doc)


def update_doc(doc_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        doc = load_doc(doc_id)
        doc.update(fields)
        save_doc(doc)
        return doc


def list_docs() -> list[dict[str, Any]]:
    docs = []
    for p in DOCS_DIR.iterdir():
        if (p / "doc.json").exists():
            try:
                docs.append(load_doc(p.name))
            except (json.JSONDecodeError, KeyError):
                continue
    return sorted(docs, key=lambda d: d["created"], reverse=True)


def find_page(doc: dict[str, Any], page_id: str) -> dict[str, Any]:
    for page in doc["pages"]:
        if page["id"] == page_id:
            return page
    raise KeyError(page_id)
