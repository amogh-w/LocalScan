-- Soft delete: a trashed document keeps its pages and files until it is purged (by hand or after 30 days).

ALTER TABLE documents ADD COLUMN deleted_at REAL;
CREATE INDEX documents_deleted ON documents (deleted_at);
