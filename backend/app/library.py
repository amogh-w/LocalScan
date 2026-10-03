"""Folders and tags."""
import time
from typing import Any

from . import storage
from .db import connection as db

TAG_COLORS = ("blue", "green", "peach", "mauve", "teal", "red", "yellow", "pink",
              "sapphire", "lavender", "maroon", "sky", "flamingo", "rosewater")


class LibraryError(ValueError):
    """Invalid folder/tag operation (shown to the user)."""


# --- folders ---------------------------------------------------------------------------------------

def list_folders() -> list[dict[str, Any]]:
    """Flat list (the client builds the tree), each with the number of documents directly inside."""
    rows = db.conn().execute(
        """SELECT f.id, f.parent_id, f.name, f.position,
                  (SELECT COUNT(*) FROM documents d WHERE d.folder_id = f.id) AS count
           FROM folders f ORDER BY f.position, f.name COLLATE NOCASE"""
    ).fetchall()
    return [dict(r) for r in rows]


def _folder_exists(c, folder_id: str) -> bool:
    return c.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone() is not None


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise LibraryError("name must not be empty")
    return name


def create_folder(name: str, parent_id: str | None = None) -> dict[str, Any]:
    name = _clean_name(name)
    with db.transaction() as c:
        if parent_id and not _folder_exists(c, parent_id):
            raise LibraryError("parent folder not found")
        position = c.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM folders WHERE parent_id IS ?",
                             (parent_id,)).fetchone()[0]
        fid = storage.new_id()
        c.execute("INSERT INTO folders (id, parent_id, name, position, created) VALUES (?, ?, ?, ?, ?)",
                  (fid, parent_id, name, position, time.time()))
    return next(f for f in list_folders() if f["id"] == fid)


def _ancestors(c, folder_id: str | None) -> set[str]:
    seen: set[str] = set()
    while folder_id and folder_id not in seen:
        seen.add(folder_id)
        row = c.execute("SELECT parent_id FROM folders WHERE id = ?", (folder_id,)).fetchone()
        folder_id = row["parent_id"] if row else None
    return seen


def update_folder(folder_id: str, *, name: str | None = None, parent_id: str | None = None,
                  move: bool = False) -> dict[str, Any]:
    """Rename and/or move (move=True with parent_id None means top level)."""
    with db.transaction() as c:
        if not _folder_exists(c, folder_id):
            raise KeyError(folder_id)
        if name is not None:
            c.execute("UPDATE folders SET name = ? WHERE id = ?", (_clean_name(name), folder_id))
        if move:
            if parent_id and not _folder_exists(c, parent_id):
                raise LibraryError("target folder not found")
            if parent_id and folder_id in _ancestors(c, parent_id):
                raise LibraryError("a folder can't be moved into itself")
            c.execute("UPDATE folders SET parent_id = ? WHERE id = ?", (parent_id, folder_id))
    return next(f for f in list_folders() if f["id"] == folder_id)


def delete_folder(folder_id: str) -> None:
    """Delete a folder; its documents and subfolders move up to its parent. Nothing else is deleted."""
    with db.transaction() as c:
        row = c.execute("SELECT parent_id FROM folders WHERE id = ?", (folder_id,)).fetchone()
        if row is None:
            raise KeyError(folder_id)
        c.execute("UPDATE documents SET folder_id = ? WHERE folder_id = ?", (row["parent_id"], folder_id))
        c.execute("UPDATE folders SET parent_id = ? WHERE parent_id = ?", (row["parent_id"], folder_id))
        c.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


# --- tags ------------------------------------------------------------------------------------------

def list_tags() -> list[dict[str, Any]]:
    rows = db.conn().execute(
        """SELECT t.id, t.name, t.color, COUNT(dt.doc_id) AS count
           FROM tags t LEFT JOIN document_tags dt ON dt.tag_id = t.id
           GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()
    return [dict(r) for r in rows]


def _check_color(color: str) -> str:
    if color not in TAG_COLORS:
        raise LibraryError(f"color must be one of {', '.join(TAG_COLORS)}")
    return color


def create_tag(name: str, color: str | None = None) -> dict[str, Any]:
    name = _clean_name(name)
    with db.transaction() as c:
        existing = c.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if existing:  # creating an existing tag (any case) just returns it
            tid = existing["id"]
        else:
            n = c.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            tid = storage.new_id()
            c.execute("INSERT INTO tags (id, name, color, created) VALUES (?, ?, ?, ?)",
                      (tid, name, _check_color(color) if color else TAG_COLORS[n % len(TAG_COLORS)], time.time()))
    return next(t for t in list_tags() if t["id"] == tid)


def update_tag(tag_id: str, *, name: str | None = None, color: str | None = None) -> dict[str, Any]:
    with db.transaction() as c:
        if c.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone() is None:
            raise KeyError(tag_id)
        if name is not None:
            name = _clean_name(name)
            clash = c.execute("SELECT 1 FROM tags WHERE name = ? AND id != ?", (name, tag_id)).fetchone()
            if clash:
                raise LibraryError(f'a tag called "{name}" already exists')
            c.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
        if color is not None:
            c.execute("UPDATE tags SET color = ? WHERE id = ?", (_check_color(color), tag_id))
    return next(t for t in list_tags() if t["id"] == tag_id)


def delete_tag(tag_id: str) -> None:
    with db.transaction() as c:
        if c.execute("DELETE FROM tags WHERE id = ?", (tag_id,)).rowcount == 0:
            raise KeyError(tag_id)


# --- documents in the library ----------------------------------------------------------------------

def set_folder(doc_ids: list[str], folder_id: str | None) -> None:
    with db.transaction() as c:
        if folder_id and not _folder_exists(c, folder_id):
            raise LibraryError("folder not found")
        c.executemany("UPDATE documents SET folder_id = ? WHERE id = ?", [(folder_id, d) for d in doc_ids])


def set_tags(doc_id: str, tag_ids: list[str]) -> None:
    with db.transaction() as c:
        _check_tags(c, tag_ids)
        c.execute("DELETE FROM document_tags WHERE doc_id = ?", (doc_id,))
        c.executemany("INSERT OR IGNORE INTO document_tags (doc_id, tag_id) VALUES (?, ?)",
                      [(doc_id, t) for t in dict.fromkeys(tag_ids)])


def add_tag(doc_ids: list[str], tag_id: str) -> None:
    with db.transaction() as c:
        _check_tags(c, [tag_id])
        c.executemany("INSERT OR IGNORE INTO document_tags (doc_id, tag_id) VALUES (?, ?)",
                      [(d, tag_id) for d in doc_ids])


def remove_tag(doc_ids: list[str], tag_id: str) -> None:
    with db.transaction() as c:
        c.executemany("DELETE FROM document_tags WHERE doc_id = ? AND tag_id = ?", [(d, tag_id) for d in doc_ids])


def _check_tags(c, tag_ids: list[str]) -> None:
    for t in tag_ids:
        if c.execute("SELECT 1 FROM tags WHERE id = ?", (t,)).fetchone() is None:
            raise LibraryError("tag not found")
