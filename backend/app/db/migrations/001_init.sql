-- Documents, pages and outputs. Files live in the blob store; these tables reference them by sha256.

CREATE TABLE blobs (
    sha TEXT PRIMARY KEY,          -- sha256 of the content
    ext TEXT NOT NULL,             -- file extension, e.g. jpg, pdf
    size INTEGER NOT NULL,
    created REAL NOT NULL
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_source TEXT NOT NULL DEFAULT 'manual',   -- default | manual | ai
    status TEXT NOT NULL DEFAULT 'draft',          -- draft | queued | processing | done | error
    progress TEXT,                                 -- JSON {step, done, total} while processing
    error TEXT,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX documents_created ON documents (created DESC);

CREATE TABLE pages (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    original_blob TEXT NOT NULL REFERENCES blobs (sha),
    clean_blob TEXT REFERENCES blobs (sha),
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'photo',          -- photo | pdf
    corners TEXT NOT NULL,                         -- JSON [[x, y] * 4], normalised
    detected TEXT NOT NULL,                        -- JSON, corners found on upload
    rotation INTEGER NOT NULL DEFAULT 0,
    filter TEXT NOT NULL DEFAULT 'enhanced',
    clean_key TEXT,                                -- cache key of clean_blob
    ocr_key TEXT,                                  -- cache key of lines
    lines TEXT,                                    -- JSON OCR lines
    pdf_lines TEXT                                 -- JSON text-layer lines of imported digital PDFs
);
CREATE INDEX pages_doc ON pages (doc_id, position);

CREATE TABLE outputs (
    doc_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                            -- scan | translated | side_by_side
    blob TEXT NOT NULL REFERENCES blobs (sha),
    created REAL NOT NULL,
    PRIMARY KEY (doc_id, kind)
);

-- Translations of text blocks, shared by all documents (key = engine, model, prompt, languages, text).
CREATE TABLE translation_cache (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL
);

-- Rendered previews/thumbnails, keyed by everything that affects the pixels.
CREATE TABLE previews (
    key TEXT PRIMARY KEY,
    page_id TEXT NOT NULL,                         -- no FK: cleaned up when the page is gone
    blob TEXT NOT NULL REFERENCES blobs (sha),
    created REAL NOT NULL
);
CREATE INDEX previews_page ON previews (page_id);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
