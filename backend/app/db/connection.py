"""SQLite connection per thread, WAL mode, re-entrant write transactions, schema migrations."""
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"

_local = threading.local()
_db_path: Path | None = None


def init(db_path: Path) -> None:
    """Point the module at a database file and bring its schema up to date."""
    global _db_path
    close()
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(conn())


def conn() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db.init() was not called")
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != _db_path:
        c = sqlite3.connect(_db_path, isolation_level=None, check_same_thread=False, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn, _local.path, _local.depth = c, _db_path, 0
    return c


def close() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE write transaction; nested calls join the outer one."""
    c = conn()
    if _local.depth:
        _local.depth += 1
        try:
            yield c
        finally:
            _local.depth -= 1
        return
    c.execute("BEGIN IMMEDIATE")
    _local.depth = 1
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        _local.depth = 0


def migrate(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = c.execute("SELECT version FROM schema_version").fetchone()
    current = row[0] if row else 0
    for f in sorted(MIGRATIONS.glob("*.sql")):
        version = int(f.name.split("_", 1)[0])
        if version <= current:
            continue
        # Schema change and version bump commit together, so a crash never leaves half a migration.
        c.executescript(
            "BEGIN;\n" + f.read_text("utf-8")
            + f"\nDELETE FROM schema_version;\nINSERT INTO schema_version VALUES ({version});\nCOMMIT;"
        )
