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

TRASH_DAYS = 30  # how long a trashed document is kept before it is deleted for good
JSON_PAGE_FIELDS = ("corners", "detected", "lines", "pdf_lines")


def init(data_dir: Path) -> None:
    """Open the database and blob store under data_dir, and import any old JSON documents."""
    db.init(data_dir / "localscan.db")
    blobs.init(data_dir / "blobs")
    from .db.legacy import migrate_json_docs
    migrate_json_docs(data_dir)
    purge_trash(TRASH_DAYS * 86400)


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
        "deleted_at": r["deleted_at"],
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


def list_docs(folder: str | None = None, tag: str | None = None, trashed: bool = False) -> list[dict[str, Any]]:
    """All documents, newest first. folder: a folder id, or "none" for unfiled. tag: a tag id.

    Trashed documents are left out unless trashed=True, which returns only them (latest first).
    """
    where, args = ["deleted_at IS NOT NULL" if trashed else "deleted_at IS NULL"], []
    if folder == "none":
        where.append("folder_id IS NULL")
    elif folder:
        where.append("folder_id = ?")
        args.append(folder)
    if tag:
        where.append("id IN (SELECT doc_id FROM document_tags WHERE tag_id = ?)")
        args.append(tag)
    sql = "SELECT * FROM documents WHERE " + " AND ".join(where) + (" ORDER BY deleted_at DESC" if trashed else " ORDER BY created DESC")
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


def trash_doc(doc_ids: list[str]) -> None:
    """Move documents to the trash. Nothing is deleted: restore_docs brings them back."""
    with db.transaction() as c:
        c.executemany("UPDATE documents SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                      [(time.time(), i) for i in doc_ids])


def restore_docs(doc_ids: list[str]) -> None:
    with db.transaction() as c:
        c.executemany("UPDATE documents SET deleted_at = NULL WHERE id = ?", [(i,) for i in doc_ids])


def purge_trash(older_than: float = 0, doc_ids: list[str] | None = None) -> int:
    """Delete trashed documents for good (those trashed more than `older_than` seconds ago, or the given ids)."""
    cutoff = time.time() - older_than
    with db.transaction() as c:
        rows = c.execute("SELECT id FROM documents WHERE deleted_at IS NOT NULL AND deleted_at <= ?", (cutoff,)).fetchall()
        ids = [r["id"] for r in rows if doc_ids is None or r["id"] in doc_ids]
        c.executemany("DELETE FROM documents WHERE id = ?", [(i,) for i in ids])
    if ids:
        collect_garbage()
    return len(ids)


def trash_pages(source_id: str, page_ids: list[str]) -> str:
    """Keep deleted pages: they go to the trash as a document of their own, and the caller then removes
    them from the source. Restoring that document gives the pages back as a separate document."""
    count = len(page_ids)
    name = f"{load_doc(source_id)['name']} (deleted page{'s' if count != 1 else ''})"
    (doc,) = create_documents_from_pages(source_id, [{"page_ids": page_ids, "name": name}])
    trash_doc([doc["id"]])
    return doc["id"]


def delete_doc(doc_id: str) -> None:
    """Delete a document for good (the trash calls this through purge_trash; the app itself uses trash_doc)."""
    with db.transaction() as c:
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    collect_garbage()


def collect_garbage() -> int:
    """Drop previews of pages that no longer exist, then blobs nothing refers to."""
    with db.transaction() as c:
        c.execute("DELETE FROM previews WHERE page_id NOT IN (SELECT id FROM pages)")
    return blobs.gc()


def create_documents_from_pages(source_id: str, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """New documents holding COPIES of pages of `source_id`; the source is left untouched.

    groups: [{page_ids: [...], name: str, name_source: "ai" | "manual"}]. A copy gets a new page id but shares
    the photo and cleaned-image blobs and keeps the OCR, crop and filter, so nothing is read or processed
    again. The new documents get the source's folder and tags. All or nothing: a bad page id creates nothing.
    """
    with db.transaction() as c:
        source = load_doc(source_id)
        by_id = {p["id"]: p for p in source["pages"]}
        created = []
        for n, group in enumerate(groups, 1):
            ids = group["page_ids"]
            if not ids or len(set(ids)) != len(ids):
                raise ValueError("each document needs its pages listed once")
            missing = [i for i in ids if i not in by_id]
            if missing:
                raise KeyError(missing[0])
            name = (group.get("name") or "").strip()[:120]
            doc = create_doc(name or f"{source['name']} (part {n})",
                             group.get("name_source", "manual") if name else "manual")
            doc["pages"] = [{**by_id[i], "id": new_id()} for i in ids]
            doc["folder_id"] = source["folder_id"]
            save_doc(doc)
            c.execute("INSERT INTO document_tags (doc_id, tag_id) SELECT ?, tag_id FROM document_tags WHERE doc_id = ?",
                      (doc["id"], source_id))
            created.append(doc["id"])
    return [load_doc(i) for i in created]


KEEP = object()  # move_pages: "leave the new document in the source's folder"


def _page_label(positions: list[int]) -> str:
    """"page 3", "pages 2-4" or "pages 1, 3, 5" for 0-based positions."""
    nums = [p + 1 for p in positions]
    if len(nums) == 1:
        return f"page {nums[0]}"
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"pages {nums[0]}-{nums[-1]}"
    return "pages " + ", ".join(map(str, nums))


def _renumber(c, doc_id: str, order: list[str]) -> None:
    c.executemany("UPDATE pages SET doc_id = ?, position = ? WHERE id = ?", [(doc_id, i, p) for i, p in enumerate(order)])


def _mark_draft(c, *doc_ids: str) -> None:
    c.executemany("UPDATE documents SET status = 'draft', updated = ? WHERE id = ? AND status IN ('done', 'error')",
                  [(time.time(), d) for d in doc_ids])


def move_pages(source_id: str, page_ids: list[str], folder: Any = KEEP, name: str = "") -> tuple[dict[str, Any], list[int]]:
    """Move pages out of a document into a new one. The pages keep their ids, OCR and previews.

    folder: KEEP (the source's folder), a folder id, or None (unfiled). Returns (the new document, the pages'
    old 0-based positions in the order they were moved), which return_pages needs to undo the move. The new
    document inherits the source's tags; both documents go back to draft. All or nothing.
    """
    with db.transaction() as c:
        source = load_doc(source_id)
        order = [p["id"] for p in source["pages"]]
        if not page_ids or len(set(page_ids)) != len(page_ids):
            raise ValueError("list each page once")
        for pid in page_ids:
            if pid not in order:
                raise KeyError(pid)
        if folder is not KEEP and folder is not None and not c.execute("SELECT 1 FROM folders WHERE id = ?", (folder,)).fetchone():
            raise ValueError("folder not found")
        chosen = set(page_ids)
        moving = [pid for pid in order if pid in chosen]  # document order
        positions = [order.index(pid) for pid in moving]
        new = create_doc((name or "").strip()[:120] or f"{source['name']} ({_page_label(positions)})")
        _renumber(c, new["id"], moving)
        _renumber(c, source_id, [pid for pid in order if pid not in chosen])
        c.execute("UPDATE documents SET folder_id = ? WHERE id = ?",
                  (source["folder_id"] if folder is KEEP else folder, new["id"]))
        c.execute("INSERT INTO document_tags (doc_id, tag_id) SELECT ?, tag_id FROM document_tags WHERE doc_id = ?",
                  (new["id"], source_id))
        _mark_draft(c, source_id, new["id"])
    return load_doc(new["id"]), positions


def return_pages(from_id: str, page_ids: list[str], to_id: str, positions: list[int]) -> dict[str, Any]:
    """Undo of move_pages: put the pages back into `to_id` at their old positions. The document they came
    from is deleted when nothing is left in it."""
    if len(positions) != len(page_ids):
        raise ValueError("positions must match the pages")
    with db.transaction() as c:
        held_pages = load_doc(from_id)["pages"]
        held = {p["id"] for p in held_pages}
        for pid in page_ids:
            if pid not in held:
                raise KeyError(pid)
        target = [p["id"] for p in load_doc(to_id)["pages"]]
        for pos, pid in sorted(zip(positions, page_ids)):
            target.insert(min(max(pos, 0), len(target)), pid)
        _renumber(c, to_id, target)
        rest = [p["id"] for p in held_pages if p["id"] not in set(page_ids)]
        _renumber(c, from_id, rest)
        if rest:
            _mark_draft(c, from_id)
        else:
            c.execute("DELETE FROM documents WHERE id = ?", (from_id,))
        _mark_draft(c, to_id)
    collect_garbage()
    return load_doc(to_id)


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


def delete_translations(keys: Iterable[str]) -> None:
    keys = list(dict.fromkeys(keys))
    with db.transaction() as c:
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            c.execute(f"DELETE FROM translation_cache WHERE key IN ({','.join('?' * len(part))})", part)


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
