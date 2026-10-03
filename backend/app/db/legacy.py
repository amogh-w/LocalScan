"""One-time import of the old JSON layout (data/docs/<id>/doc.json + files) into the database.

Keeps OCR and translations: a page's cached OCR stays valid when it matched the page under the old
cache key, and is re-keyed for the new blob-based key. The old folder is renamed, never deleted.
"""
import hashlib
import json
import logging
import re
import time
from pathlib import Path

from . import blobs
from . import connection as db

log = logging.getLogger(__name__)

LEGACY_OUTPUT_FILES = {"scan": "scan.pdf", "translated": "translated.pdf", "side_by_side": "side_by_side.pdf"}
DEFAULT_NAME = re.compile(r"^Scan \d{4}-\d{2}-\d{2} \d{2}-\d{2}$")


def _legacy_clean_key(page: dict, scan_version: int) -> str:
    raw = json.dumps([scan_version, page["file"], page["corners"], page["rotation"], page["filter"]])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def migrate_json_docs(data_dir: Path) -> int:
    from .. import jobs, storage  # late import: both depend on the db being initialised

    docs_dir = data_dir / "docs"
    manifests = sorted(docs_dir.glob("*/doc.json")) if docs_dir.is_dir() else []
    if not manifests:
        return 0
    imported = 0
    for manifest in manifests:
        d = manifest.parent
        try:
            doc = json.loads(manifest.read_text("utf-8"))
        except json.JSONDecodeError:
            log.warning("skipping unreadable %s", manifest)
            continue
        if db.conn().execute("SELECT 1 FROM documents WHERE id = ?", (doc["id"],)).fetchone():
            continue
        pages = []
        for p in doc.get("pages", []):
            original = d / p["file"]
            if not original.exists():
                log.warning("skipping page %s of %s: %s missing", p["id"], doc["id"], original)
                continue
            valid_cache = p.get("ocr_key") and p.get("ocr_key") == _legacy_clean_key(p, jobs.SCAN_VERSION)
            page = {k: v for k, v in p.items() if k != "file"}
            page["original"] = blobs.put_file(original)
            clean = d / "pages" / f"{p['id']}.clean.jpg"
            page["clean"] = blobs.put_file(clean) if valid_cache and clean.exists() else None
            key = jobs.clean_key(page)
            page["clean_key"] = key if page["clean"] else None
            page["ocr_key"] = key if valid_cache else None
            if not valid_cache:
                page["lines"] = None
            pages.append(page)
        outputs = {}
        if doc.get("status") == "done":
            for kind, fname in LEGACY_OUTPUT_FILES.items():
                if kind in doc.get("outputs", {}) and (d / fname).exists():
                    outputs[kind] = blobs.put_file(d / fname)
        source = doc.get("name_source") or ("default" if DEFAULT_NAME.match(doc.get("name", "")) else "manual")
        with db.transaction():
            storage.save_doc({
                "id": doc["id"], "name": doc.get("name") or "Untitled", "name_source": source,
                "created": doc.get("created", time.time()), "pages": pages,
                "status": doc["status"] if doc.get("status") in ("draft", "done", "error") else "draft",
                "progress": None, "error": doc.get("error"), "outputs": outputs,
            })
            if doc.get("tcache"):
                storage.cache_translations(doc["tcache"])
        imported += 1
    target = data_dir / time.strftime("docs.migrated-%Y%m%d-%H%M%S")
    docs_dir.rename(target)
    log.info("imported %d documents into the database; old files kept in %s", imported, target)
    return imported
