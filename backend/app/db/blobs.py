"""Content-addressed file store: data/blobs/<first 2 hex>/<sha256>.<ext>, indexed in the `blobs` table."""
import hashlib
import os
import time
from pathlib import Path

from . import connection as db

_root: Path | None = None


def init(root: Path) -> None:
    global _root
    _root = root
    root.mkdir(parents=True, exist_ok=True)


def _path(sha: str, ext: str) -> Path:
    if _root is None:
        raise RuntimeError("blobs.init() was not called")
    return _root / sha[:2] / f"{sha}.{ext}"


def put(data: bytes, ext: str) -> str:
    """Store bytes once; identical content is deduplicated. Returns the sha256."""
    ext = ext.lower().lstrip(".")
    sha = hashlib.sha256(data).hexdigest()
    p = _path(sha, ext)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    with db.transaction() as c:
        c.execute("INSERT OR IGNORE INTO blobs (sha, ext, size, created) VALUES (?, ?, ?, ?)",
                  (sha, ext, len(data), time.time()))
    return sha


def put_file(path: Path) -> str:
    return put(path.read_bytes(), path.suffix)


def path(sha: str) -> Path:
    row = db.conn().execute("SELECT ext FROM blobs WHERE sha = ?", (sha,)).fetchone()
    if row is None:
        raise KeyError(sha)
    return _path(sha, row["ext"])


REFERENCES = (
    "SELECT original_blob FROM pages",
    "SELECT clean_blob FROM pages WHERE clean_blob IS NOT NULL",
    "SELECT blob FROM outputs",
    "SELECT blob FROM previews",
)


GRACE_SECONDS = 600


def gc(grace: float = GRACE_SECONDS) -> int:
    """Delete blobs nothing refers to any more. Returns how many were removed.

    Blobs younger than `grace` are kept: an upload stores its blob a moment before the page row
    that references it, and must not be collected in between.
    """
    with db.transaction() as c:
        rows = c.execute(
            "SELECT sha, ext FROM blobs WHERE created < ? AND sha NOT IN (" + " UNION ".join(REFERENCES) + ")",
            (time.time() - grace,),
        ).fetchall()
        c.executemany("DELETE FROM blobs WHERE sha = ?", [(r["sha"],) for r in rows])
    for r in rows:
        _path(r["sha"], r["ext"]).unlink(missing_ok=True)
    return len(rows)
