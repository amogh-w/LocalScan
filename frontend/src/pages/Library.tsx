import QRCode from "qrcode";
import {
  Camera, FileText, Files, Folder, FolderInput, Inbox, Languages, Menu, Pencil, Plus, RotateCcw, Settings, Smartphone, Sparkles, Square,
  SquareCheck, Tag as TagIcon, Trash2, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, flattenFolders, previewUrl, type Doc, type Folder as FolderT, type LibraryView, type Tag } from "../api";
import { AiRenameButton, AiSuggestion, useAiRename } from "../components/AiRename";
import NameEditor from "../components/NameEditor";
import Sidebar, { DOC_DRAG_TYPE } from "../components/Sidebar";
import TagChip from "../components/TagChip";
import { AsyncButton, PdfLinks, StatusBadge } from "../components/common";

const isPhone = matchMedia("(pointer: coarse)").matches;

function inView(d: Doc, v: LibraryView) {
  if (v.kind === "unfiled") return !d.folder_id;
  if (v.kind === "folder") return d.folder_id === v.id;
  if (v.kind === "trash") return false;
  if (v.kind === "tag") return d.tags.some((t) => t.id === v.id);
  return true;
}

export default function Library({ view }: { view: LibraryView }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [trashed, setTrashed] = useState<Doc[]>([]);
  const [folders, setFolders] = useState<FolderT[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [colors, setColors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [qr, setQr] = useState<{ url: string; svg: string } | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawer, setDrawer] = useState(false);

  const loadLibrary = useCallback(async () => {
    try {
      const [d, f, t, bin] = await Promise.all([api.listDocs(), api.listFolders(), api.listTags(), api.listDocs({ kind: "trash" })]);
      setDocs(d);
      setTrashed(bin);
      setFolders(f);
      setTags(t.tags);
      setColors(t.colors);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    loadLibrary();
    const t = setInterval(loadLibrary, 3000);
    return () => clearInterval(t);
  }, [loadLibrary]);

  useEffect(() => {
    setSelected(new Set());
    setDrawer(false);
  }, [view.kind, "id" in view ? view.id : ""]);

  useEffect(() => {
    if (isPhone) return;
    api.serverInfo().then(async ({ lan_url }) => {
      // Same port as this page, so in dev the phone gets the Vite server with hot reload.
      const url = new URL(lan_url);
      url.port = location.port;
      const svg = await QRCode.toString(url.origin, { type: "svg", margin: 1 });
      setQr({ url: url.origin, svg });
    });
  }, []);

  const shown = useMemo(() => (view.kind === "trash" ? trashed : (docs ?? []).filter((d) => inView(d, view))), [docs, trashed, view]);
  const folderName = useMemo(() => new Map(folders.map((f) => [f.id, f.name])), [folders]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await loadLibrary();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const newScan = async () => {
    const doc = await api.createDoc();
    if (view.kind === "folder") await api.moveDoc(doc.id, view.id); // new scans land in the open folder
    if (view.kind === "tag") await api.setDocTags(doc.id, [view.id]);
    location.hash = `#/doc/${doc.id}`;
  };

  const ids = [...selected];
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const title =
    view.kind === "all" ? { icon: <Files />, text: "All documents" }
    : view.kind === "unfiled" ? { icon: <Inbox />, text: "Unfiled" }
    : view.kind === "trash" ? { icon: <Trash2 />, text: "Trash" }
    : view.kind === "folder" ? { icon: <Folder />, text: folderName.get(view.id) ?? "Folder" }
    : { icon: <TagIcon />, text: tags.find((t) => t.id === view.id)?.name ?? "Tag" };

  return (
    <div className="screen lib-screen">
      <header className="bar">
        <button className="icon-btn menu-btn" onClick={() => setDrawer(!drawer)} aria-label="Folders and tags" title="Folders and tags">
          <Menu />
        </button>
        <h1>Local Scan</h1>
        <a className="icon-btn" href="#/settings" aria-label="Settings" title="Settings">
          <Settings />
        </a>
      </header>

      <div className={`lib${drawer ? " drawer-open" : ""}`}>
        <div className="drawer-backdrop" onClick={() => setDrawer(false)} />
        <aside className="lib-side">
          <Sidebar view={view} folders={folders} tags={tags} colors={colors} total={docs?.length ?? 0}
            unfiled={(docs ?? []).filter((d) => !d.folder_id).length} trashed={trashed.length} onChanged={loadLibrary} onError={setError}
            onDropDocs={(folderId, dropped) => act(() => api.bulk(dropped, "move", { folder_id: folderId }))} />
          {qr && (
            <details className="qr-card">
              <summary className="with-icon">
                <Smartphone /> Scan from your phone
              </summary>
              <div className="qr" dangerouslySetInnerHTML={{ __html: qr.svg }} />
              <p className="muted small">
                Same Wi-Fi, open <code>{qr.url}</code>
              </p>
            </details>
          )}
        </aside>

        <main className="lib-main">
          <div className="lib-head">
            <h2 className="with-icon lib-title">
              {title.icon} {title.text} <span className="muted small">{shown.length}</span>
            </h2>
            {view.kind === "trash" ? (
              <AsyncButton className="btn danger" disabled={!trashed.length} icon={<Trash2 />}
                onClick={() => window.confirm(`Delete ${trashed.length} document${trashed.length === 1 ? "" : "s"} for good? This cannot be undone.`)
                  && act(() => api.emptyTrash())}>
                Empty trash
              </AsyncButton>
            ) : (
              <AsyncButton className="btn primary" onClick={newScan} icon={<Plus />}>
                New scan
              </AsyncButton>
            )}
          </div>

          {error && <p className="error">{error}</p>}
          {view.kind === "trash" && shown.length > 0 && (
            <p className="muted small">Documents in the trash are deleted for good after 30 days.</p>
          )}
          {docs && shown.length === 0 && view.kind === "trash" && (
            <div className="empty-state lib-empty">
              <Trash2 />
              <p>The trash is empty.</p>
            </div>
          )}
          {docs && shown.length === 0 && view.kind !== "trash" && (
            <div className="empty-state lib-empty">
              {title.icon}
              <p>{docs.length === 0 ? "No documents yet. Start with New scan." : "Nothing here yet. Drag documents onto a folder to file them."}</p>
            </div>
          )}

          <ul className="doc-grid">
            {shown.map((d) => view.kind === "trash" ? (
              <TrashCard key={d.id} doc={d}
                onRestore={() => act(() => api.bulk([d.id], "restore"))}
                onPurge={() => window.confirm(`Delete "${d.name}" for good? This cannot be undone.`)
                  && act(() => api.bulk([d.id], "purge"))} />
            ) : (
              <DocCard key={d.id} doc={d} folderName={view.kind !== "folder" && d.folder_id ? folderName.get(d.folder_id) : undefined}
                selected={selected.has(d.id)} selecting={selected.size > 0} onToggle={() => toggle(d.id)}
                dragIds={selected.has(d.id) ? ids : [d.id]} onError={setError}
                onChange={(saved) => setDocs((all) => all && all.map((x) => (x.id === saved.id ? saved : x)))} />
            ))}
          </ul>
        </main>
      </div>

      {selected.size > 0 && (
        <BulkBar count={selected.size} folders={folders} tags={tags}
          onClear={() => setSelected(new Set())}
          onSelectAll={() => setSelected(new Set(shown.map((d) => d.id)))}
          onMove={(folderId) => act(() => api.bulk(ids, "move", { folder_id: folderId }))}
          onTag={(tagId) => act(() => api.bulk(ids, "tag", { tag_id: tagId }))}
          onDelete={() => window.confirm(`Move ${ids.length} document${ids.length === 1 ? "" : "s"} to the trash?`)
            && act(async () => {
              await api.bulk(ids, "delete");
              setSelected(new Set());
            })} />
      )}
    </div>
  );
}

function BulkBar(p: {
  count: number; folders: FolderT[]; tags: Tag[]; onClear: () => void; onSelectAll: () => void;
  onMove: (folderId: string | null) => void; onTag: (tagId: string) => void; onDelete: () => unknown;
}) {
  return (
    <div className="bulk-bar" role="toolbar" aria-label="Selected documents">
      <span className="bulk-count">{p.count} selected</span>
      <button className="btn small" onClick={p.onSelectAll}>Select all</button>
      <label className="btn small select-btn">
        <FolderInput /> Move to
        <select value="" onChange={(e) => e.target.value && p.onMove(e.target.value === "__none" ? null : e.target.value)}>
          <option value="" disabled>Move to…</option>
          <option value="__none">Unfiled</option>
          {flattenFolders(p.folders).map((f) => (
            <option key={f.id} value={f.id}>{"  ".repeat(f.depth) + f.name}</option>
          ))}
        </select>
      </label>
      <label className="btn small select-btn">
        <TagIcon /> Add tag
        <select value="" onChange={(e) => e.target.value && p.onTag(e.target.value)} disabled={!p.tags.length}>
          <option value="" disabled>{p.tags.length ? "Add tag…" : "No tags yet"}</option>
          {p.tags.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </label>
      <AsyncButton className="btn small danger" onClick={p.onDelete} icon={<Trash2 />}>
        Move to trash
      </AsyncButton>
      <button className="icon-btn" onClick={p.onClear} aria-label="Clear selection" title="Clear selection">
        <X />
      </button>
    </div>
  );
}

function TrashCard({ doc: d, onRestore, onPurge }: { doc: Doc; onRestore: () => unknown; onPurge: () => unknown }) {
  const first = d.pages[0];
  const left = Math.max(0, 30 - Math.floor((Date.now() / 1000 - (d.deleted_at ?? 0)) / 86400));
  return (
    <li className="tile card">
      <div className="tile-thumb">
        {first ? <img src={previewUrl(d.id, first, 400)} alt="" draggable={false} loading="lazy" />
          : <div className="tile-empty"><FileText /><span>No pages</span></div>}
      </div>
      <div className="tile-body">
        <span className="tile-title" title={d.name}>{d.name}</span>
        <div className="tile-meta">
          {d.pages.length} page{d.pages.length === 1 ? "" : "s"} · deleted for good in {left} day{left === 1 ? "" : "s"}
        </div>
      </div>
      <div className="tile-foot actions">
        <AsyncButton onClick={onRestore} icon={<RotateCcw />}>Restore</AsyncButton>
        <AsyncButton className="btn small danger" onClick={onPurge} icon={<Trash2 />}>Delete forever</AsyncButton>
      </div>
    </li>
  );
}

function DocCard({ doc: d, folderName, selected, selecting, onToggle, dragIds, onChange, onError }: {
  doc: Doc; folderName?: string; selected: boolean; selecting: boolean; onToggle: () => void; dragIds: string[];
  onChange: (doc: Doc) => void; onError: (m: string) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const ai = useAiRename(d, onChange, onError);
  const first = d.pages[0];
  const href = `#/doc/${d.id}`;
  // While selecting, clicking the card toggles it instead of opening it.
  const open = (e: React.MouseEvent) => {
    if (selecting) {
      e.preventDefault();
      onToggle();
    }
  };

  const rename = async (name: string) => {
    try {
      onChange(await api.renameDoc(d.id, name));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  // Documents that aren't finished get one clear next step instead of PDF buttons.
  const next =
    d.status === "draft" ? (d.pages.length ? { label: "Review & translate", icon: <Languages /> } : { label: "Add pages", icon: <Camera /> })
    : d.status === "error" ? { label: "Open to retry", icon: <Languages /> }
    : null;

  return (
    <li className={`tile card${selected ? " selected" : ""}${selecting ? " selecting" : ""}`}
      draggable={!renaming}
      onDragStart={(e) => {
        e.dataTransfer.setData(DOC_DRAG_TYPE, JSON.stringify(dragIds));
        e.dataTransfer.effectAllowed = "move";
      }}>
      <div className="tile-thumb">
        <a href={href} onClick={open} draggable={false} tabIndex={-1} aria-label={`Open ${d.name}`}>
          {first ? (
            <img src={previewUrl(d.id, first, 400)} alt="" draggable={false} loading="lazy" />
          ) : (
            <div className="tile-empty">
              <FileText />
              <span>No pages yet</span>
            </div>
          )}
        </a>
        <button className="select-box" onClick={onToggle} aria-pressed={selected}
          aria-label={selected ? `Deselect ${d.name}` : `Select ${d.name}`} title={selected ? "Deselect" : "Select"}>
          {selected ? <SquareCheck /> : <Square />}
        </button>
        {!renaming && (
          <div className="tile-actions">
            <AiRenameButton ai={ai} doc={d} />
            <button className="icon-btn" onClick={() => setRenaming(true)} aria-label={`Rename ${d.name}`} title="Rename">
              <Pencil />
            </button>
          </div>
        )}
      </div>

      <div className="tile-body">
        {renaming ? (
          <NameEditor value={d.name} autoFocus className="title-input tile-rename" label="Document name"
            onSave={rename} onDone={() => setRenaming(false)} />
        ) : (
          <a className="tile-title" href={href} onClick={open} draggable={false} title={d.name}>
            {d.name_source === "ai" && (
              <span className="ai-mark" title="Named by AI">
                <Sparkles />
              </span>
            )}
            {d.name}
          </a>
        )}
        <div className="tile-meta">
          {d.pages.length} page{d.pages.length === 1 ? "" : "s"} ·{" "}
          {new Date(d.created * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        </div>
        <AiSuggestion ai={ai} />
        {(folderName || d.tags.length > 0) && (
          <div className="tile-tags">
            {folderName && (
              <span className="folder-chip">
                <Folder /> {folderName}
              </span>
            )}
            {d.tags.map((t) => (
              <TagChip key={t.id} tag={t} />
            ))}
          </div>
        )}
        {/* Finished documents show their PDFs and unstarted ones their next step; the badge is for in-between states. */}
        {(d.status === "queued" || d.status === "processing" || d.status === "error") && <StatusBadge doc={d} />}
      </div>

      {d.status === "done" ? (
        <div className="tile-foot">
          <PdfLinks doc={d} />
        </div>
      ) : (
        next && (
          <div className="tile-foot">
            <a className="btn small tile-cta" href={href}>
              {next.icon} {next.label}
            </a>
          </div>
        )
      )}
    </li>
  );
}
