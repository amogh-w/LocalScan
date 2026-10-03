"""Documents in SQLite (data/localscan.db); images and PDFs in the blob store (data/blobs/).

The functions return/accept the same document dicts the rest of the app has always used:
  {id, name, name_source, created, status, progress, error, outputs: {kind: sha}, pages: [page, ...]}
  page: {id, original, clean, width, height, source, corners, detected, rotation, filter,
         clean_key, ocr_key, lines, pdf_lines}
"""
import json
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .db import blobs
from .db import connection as db

JSON_PAGE_FIELDS = ("corners", "detected", "lines", "pdf_lines")


def init(data_dir: Path) -> None:
    """Open the database and blob store under data_dir, and import any old JSON documents."""
    db.init(data_dir / "localscan.db")
    blobs.init(data_dir / "blobs")
    from .db.legacy import migrate_json_docs
    migrate_json_docs(data_dir)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _page_from_row(r) -> dict[str, Any]:
    page = {
        "id": r["id"], "original": r["original_blob"], "clean": r["clean_blob"],
        "width": r["width"], "height": r["height"], "source": r["source"],
        "rotation": r["rotation"], "filter": r["filter"],
        "clean_key": r["clean_key"], "ocr_key": r["ocr_key"],
    }
    for f in JSON_PAGE_FIELDS:
        page[f] = json.loads(r[f]) if r[f] is not None else None
    return page


def _docs_from_rows(rows: Iterable) -> list[dict[str, Any]]:
    docs = [{
        "id": r["id"], "name": r["name"], "name_source": r["name_source"], "created": r["created"],
        "status": r["status"], "progress": json.loads(r["progress"]) if r["progress"] else None,
        "error": r["error"], "outputs": {}, "pages": [], "folder_id": r["folder_id"], "tags": [],
    } for r in rows]
    if not docs:
        return docs
    by_id = {d["id"]: d for d in docs}
    marks = ",".join("?" * len(by_id))
    c = db.conn()
    for r in c.execute(f"SELECT * FROM pages WHERE doc_id IN ({marks}) ORDER BY doc_id, position", list(by_id)):
        by_id[r["doc_id"]]["pages"].append(_page_from_row(r))
    for r in c.execute(f"SELECT doc_id, kind, blob FROM outputs WHERE doc_id IN ({marks})", list(by_id)):
        by_id[r["doc_id"]]["outputs"][r["kind"]] = r["blob"]
    for r in c.execute(
        f"""SELECT dt.doc_id, t.id, t.name, t.color FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
            WHERE dt.doc_id IN ({marks}) ORDER BY t.name COLLATE NOCASE""", list(by_id)):
        by_id[r["doc_id"]]["tags"].append({"id": r["id"], "name": r["name"], "color": r["color"]})
    return docs


def load_doc(doc_id: str) -> dict[str, Any]:
    rows = db.conn().execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchall()
    if not rows:
        raise KeyError(doc_id)
    return _docs_from_rows(rows)[0]


def list_docs(folder: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
    """All documents, newest first. folder: a folder id, or "none" for unfiled. tag: a tag id."""
    where, args = [], []
    if folder == "none":
        where.append("folder_id IS NULL")
    elif folder:
        where.append("folder_id = ?")
        args.append(folder)
    if tag:
        where.append("id IN (SELECT doc_id FROM document_tags WHERE tag_id = ?)")
        args.append(tag)
    sql = "SELECT * FROM documents" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created DESC"
    return _docs_from_rows(db.conn().execute(sql, args).fetchall())


def save_doc(doc: dict[str, Any]) -> None:
    """Write the whole document (row, pages in order, outputs) in one transaction."""
    now = time.time()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO documents (id, name, name_source, status, progress, error, created, updated, folder_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET name = excluded.name, name_source = excluded.name_source,
                 status = excluded.status, progress = excluded.progress, error = excluded.error,
                 updated = excluded.updated, folder_id = excluded.folder_id""",
            (doc["id"], doc["name"], doc.get("name_source", "manual"), doc["status"],
             json.dumps(doc["progress"]) if doc.get("progress") else None, doc.get("error"),
             doc["created"], now, doc.get("folder_id")),
        )
        ids = [p["id"] for p in doc["pages"]]
        c.execute(f"DELETE FROM pages WHERE doc_id = ? AND id NOT IN ({','.join('?' * len(ids))})",
                  [doc["id"], *ids])
        for pos, p in enumerate(doc["pages"]):
            c.execute(
                """INSERT INTO pages (id, doc_id, position, original_blob, clean_blob, width, height, source,
                     corners, detected, rotation, filter, clean_key, ocr_key, lines, pdf_lines)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET position = excluded.position, clean_blob = excluded.clean_blob,
                     corners = excluded.corners, rotation = excluded.rotation, filter = excluded.filter,
                     detected = excluded.detected, clean_key = excluded.clean_key, ocr_key = excluded.ocr_key,
                     lines = excluded.lines, pdf_lines = excluded.pdf_lines""",
                (p["id"], doc["id"], pos, p["original"], p.get("clean"), p["width"], p["height"],
                 p.get("source", "photo"), json.dumps(p["corners"]), json.dumps(p.get("detected") or p["corners"]),
                 p.get("rotation", 0), p.get("filter", "enhanced"), p.get("clean_key"), p.get("ocr_key"),
                 json.dumps(p["lines"]) if p.get("lines") is not None else None,
                 json.dumps(p["pdf_lines"]) if p.get("pdf_lines") is not None else None),
            )
        c.execute("DELETE FROM outputs WHERE doc_id = ?", (doc["id"],))
        c.executemany("INSERT INTO outputs (doc_id, kind, blob, created) VALUES (?, ?, ?, ?)",
                      [(doc["id"], k, sha, now) for k, sha in doc.get("outputs", {}).items()])


def create_doc(name: str, name_source: str = "manual") -> dict[str, Any]:
    doc = {"id": new_id(), "name": name, "name_source": name_source, "created": time.time(), "pages": [],
           "status": "draft", "progress": None, "error": None, "outputs": {}, "folder_id": None, "tags": []}
    save_doc(doc)
    return doc


@contextmanager
def editing(doc_id: str) -> Iterator[dict[str, Any]]:
    """Load, change and save a document as one transaction, so concurrent edits can't overwrite each other."""
    with db.transaction():
        doc = load_doc(doc_id)
        yield doc
        save_doc(doc)


def update_doc(doc_id: str, **fields: Any) -> dict[str, Any]:
    with editing(doc_id) as doc:
        doc.update(fields)
    return doc


def delete_doc(doc_id: str) -> None:
    with db.transaction() as c:
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    collect_garbage()


def collect_garbage() -> int:
    """Drop previews of pages that no longer exist, then blobs nothing refers to."""
    with db.transaction() as c:
        c.execute("DELETE FROM previews WHERE page_id NOT IN (SELECT id FROM pages)")
    return blobs.gc()


def find_page(doc: dict[str, Any], page_id: str) -> dict[str, Any]:
    for page in doc["pages"]:
        if page["id"] == page_id:
            return page
    raise KeyError(page_id)


# --- translation cache, shared by all documents --------------------------------------------------

def cached_translations(keys: Iterable[str]) -> dict[str, str]:
    keys = list(dict.fromkeys(keys))
    out: dict[str, str] = {}
    c = db.conn()
    for i in range(0, len(keys), 500):  # stay under SQLite's variable limit
        part = keys[i:i + 500]
        q = f"SELECT key, text FROM translation_cache WHERE key IN ({','.join('?' * len(part))})"
        out.update({r["key"]: r["text"] for r in c.execute(q, part)})
    return out


def cache_translations(items: dict[str, str]) -> None:
    with db.transaction() as c:
        c.executemany("INSERT OR REPLACE INTO translation_cache (key, text) VALUES (?, ?)", items.items())


# --- rendered previews ---------------------------------------------------------------------------

def cached_preview(key: str) -> Path | None:
    row = db.conn().execute("SELECT blob FROM previews WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        p = blobs.path(row["blob"])
    except KeyError:
        return None
    return p if p.exists() else None


def cache_preview(key: str, page_id: str, data: bytes, ext: str = "jpg") -> None:
    sha = blobs.put(data, ext)
    with db.transaction() as c:
        c.execute("INSERT OR REPLACE INTO previews (key, page_id, blob, created) VALUES (?, ?, ?, ?)",
                  (key, page_id, sha, time.time()))
