import { useEffect, useState } from "react";
import { FolderTree, Plus } from "lucide-react";
import { api, flattenFolders, type Doc, type Folder, type Tag } from "../api";
import TagChip from "./TagChip";

interface Props {
  doc: Doc;
  onChange: (doc: Doc) => void;
  onError: (message: string) => void;
}

/** "Organize" group in the Options panel: folder and tags of the document. */
export default function Organize({ doc, onChange, onError }: Props) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [draft, setDraft] = useState("");

  const load = () =>
    Promise.all([api.listFolders(), api.listTags()])
      .then(([f, t]) => (setFolders(f), setTags(t.tags)))
      .catch((e) => onError(String(e.message ?? e)));

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<Doc>) => {
    try {
      onChange(await fn());
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const current = doc.tags.map((t) => t.id);
  const addTag = async (name: string) => {
    name = name.trim();
    if (!name) return;
    const existing = tags.find((t) => t.name.toLowerCase() === name.toLowerCase());
    try {
      const tag = existing ?? (await api.createTag(name));
      if (!existing) setTags((all) => [...all, tag]);
      if (!current.includes(tag.id)) await run(() => api.setDocTags(doc.id, [...current, tag.id]));
      setDraft("");
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const available = tags.filter((t) => !current.includes(t.id));

  return (
    <section className="opt-group organize wide">
      <h3 className="with-icon"><FolderTree /> Organize</h3>
      <label className="field">
        <span className="field-label">Folder</span>
        <select value={doc.folder_id ?? ""} onChange={(e) => run(() => api.moveDoc(doc.id, e.target.value || null))}>
          <option value="">Unfiled</option>
          {flattenFolders(folders).map((f) => (
            <option key={f.id} value={f.id}>{"  ".repeat(f.depth) + f.name}</option>
          ))}
        </select>
      </label>
      <div className="field">
        <span className="field-label">Tags</span>
        {doc.tags.length > 0 && (
          <div className="tag-list">
            {doc.tags.map((t) => (
              <TagChip key={t.id} tag={t}
                onRemove={() => run(() => api.setDocTags(doc.id, current.filter((id) => id !== t.id)))} />
            ))}
          </div>
        )}
        <form className="tag-add" onSubmit={(e) => (e.preventDefault(), addTag(draft))}>
          <input list={`tags-${doc.id}`} value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder={available.length ? "Add a tag…" : "New tag…"} aria-label="Add a tag" maxLength={80} />
          <datalist id={`tags-${doc.id}`}>
            {available.map((t) => (
              <option key={t.id} value={t.name} />
            ))}
          </datalist>
          <button className="btn small" type="submit" disabled={!draft.trim()} aria-label="Add tag" title="Add tag">
            <Plus />
          </button>
        </form>
      </div>
    </section>
  );
}
