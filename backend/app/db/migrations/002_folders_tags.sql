-- Folders (a tree) and tags (many-to-many with documents).

CREATE TABLE folders (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES folders (id) ON DELETE CASCADE,  -- code moves contents up before deleting
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE INDEX folders_parent ON folders (parent_id, position);

ALTER TABLE documents ADD COLUMN folder_id TEXT REFERENCES folders (id) ON DELETE SET NULL;
CREATE INDEX documents_folder ON documents (folder_id);

CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color TEXT NOT NULL,                       -- a Catppuccin accent name, e.g. "mauve"
    created REAL NOT NULL
);

CREATE TABLE document_tags (
    doc_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (doc_id, tag_id)
);
CREATE INDEX document_tags_tag ON document_tags (tag_id);
