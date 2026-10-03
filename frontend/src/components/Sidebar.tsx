import { useState, type CSSProperties, type DragEvent } from "react";
import {
  ChevronDown, ChevronRight, Files, Folder, FolderOpen, FolderPlus, Inbox, Palette, Pencil, Plus, Trash2,
} from "lucide-react";
import { api, type Folder as FolderT, type LibraryView, type Tag } from "../api";
import NameEditor from "./NameEditor";

export const DOC_DRAG_TYPE = "application/x-localscan-docs";

interface Props {
  view: LibraryView;
  folders: FolderT[];
  tags: Tag[];
  colors: string[];
  total: number;
  unfiled: number;
  onChanged: () => void;                                   // folders/tags changed: reload
  onDropDocs: (folderId: string | null, docIds: string[]) => void;
  onError: (message: string) => void;
}

const href = (v: LibraryView) =>
  v.kind === "all" ? "#/" : v.kind === "unfiled" ? "#/unfiled" : `#/${v.kind}/${v.id}`;
const same = (a: LibraryView, b: LibraryView) => a.kind === b.kind && ("id" in a ? a.id : "") === ("id" in b ? b.id : "");

function useDrop(onDrop: (ids: string[]) => void) {
  const [over, setOver] = useState(false);
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (e.dataTransfer.types.includes(DOC_DRAG_TYPE)) {
          e.preventDefault();
          setOver(true);
        }
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: DragEvent) => {
        setOver(false);
        const raw = e.dataTransfer.getData(DOC_DRAG_TYPE);
        if (raw) onDrop(JSON.parse(raw));
      },
    },
  };
}

export default function Sidebar(p: Props) {
  const [creating, setCreating] = useState<{ kind: "folder"; parent: string | null } | { kind: "tag" } | null>(null);
  const run = async (fn: () => Promise<unknown>): Promise<void> => {
    try {
      await fn();
      p.onChanged();
    } catch (e) {
      p.onError(e instanceof Error ? e.message : String(e));
    }
  };

  const childrenOf = (parent: string | null) => p.folders.filter((f) => f.parent_id === parent);

  return (
    <nav className="sidebar" aria-label="Library">
      <div className="side-group">
        <SideLink view={{ kind: "all" }} current={p.view} icon={<Files />} label="All documents" count={p.total} />
        <DropLink view={{ kind: "unfiled" }} current={p.view} icon={<Inbox />} label="Unfiled" count={p.unfiled}
          onDrop={(ids) => p.onDropDocs(null, ids)} />
      </div>

      <div className="side-group">
        <div className="side-head">
          <span>Folders</span>
          <button className="icon-btn" title="New folder" aria-label="New folder"
            onClick={() => setCreating({ kind: "folder", parent: null })}>
            <FolderPlus />
          </button>
        </div>
        {creating?.kind === "folder" && creating.parent === null && (
          <NewItem placeholder="Folder name" onDone={() => setCreating(null)}
            onSave={(name) => run(() => api.createFolder(name))} />
        )}
        <FolderTree parent={null} depth={0} childrenOf={childrenOf} {...p} run={run} creating={creating} setCreating={setCreating} />
        {p.folders.length === 0 && creating?.kind !== "folder" && <p className="side-empty">No folders yet</p>}
      </div>

      <div className="side-group">
        <div className="side-head">
          <span>Tags</span>
          <button className="icon-btn" title="New tag" aria-label="New tag" onClick={() => setCreating({ kind: "tag" })}>
            <Plus />
          </button>
        </div>
        {creating?.kind === "tag" && (
          <NewItem placeholder="Tag name" onDone={() => setCreating(null)} onSave={(name) => run(() => api.createTag(name))} />
        )}
        {p.tags.map((t) => (
          <TagRow key={t.id} tag={t} current={p.view} colors={p.colors} run={run} />
        ))}
        {p.tags.length === 0 && creating?.kind !== "tag" && <p className="side-empty">No tags yet</p>}
      </div>
    </nav>
  );
}

function SideLink({ view, current, icon, label, count }: {
  view: LibraryView; current: LibraryView; icon: React.ReactNode; label: string; count?: number;
}) {
  return (
    <a className={`side-item${same(view, current) ? " on" : ""}`} href={href(view)}>
      {icon}
      <span className="side-label">{label}</span>
      {count !== undefined && <span className="side-count">{count}</span>}
    </a>
  );
}

function DropLink(props: Parameters<typeof SideLink>[0] & { onDrop: (ids: string[]) => void }) {
  const drop = useDrop(props.onDrop);
  return (
    <div className={drop.over ? "drop-over" : ""} {...drop.props}>
      <SideLink {...props} />
    </div>
  );
}

function NewItem({ placeholder, onSave, onDone, indent = 0 }: {
  placeholder: string; onSave: (name: string) => void; onDone: () => void; indent?: number;
}) {
  return (
    <div className="side-item editing" style={{ paddingLeft: 10 + indent * 14 }}>
      <NameEditor value="" autoFocus className="title-input side-input" label={placeholder}
        onSave={onSave} onDone={onDone} />
    </div>
  );
}

function FolderTree(props: Props & {
  parent: string | null; depth: number; childrenOf: (parent: string | null) => FolderT[];
  run: (fn: () => Promise<unknown>) => Promise<void>;
  creating: { kind: "folder"; parent: string | null } | { kind: "tag" } | null;
  setCreating: (c: { kind: "folder"; parent: string | null } | null) => void;
}) {
  return (
    <>
      {props.childrenOf(props.parent).map((f) => (
        // `props` can carry the parent row's `folder` (FolderRow spreads its props into FolderTree), so it
        // must come first: if it came after `folder={f}` it would override it and recurse forever.
        <FolderRow {...props} key={f.id} folder={f} />
      ))}
    </>
  );
}

function FolderRow(props: Parameters<typeof FolderTree>[0] & { folder: FolderT }) {
  const { folder: f, depth, view, run } = props;
  const [open, setOpen] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const drop = useDrop((ids) => props.onDropDocs(f.id, ids));
  const kids = props.childrenOf(f.id);
  const active = view.kind === "folder" && view.id === f.id;

  return (
    <>
      <div className={`side-item folder-row${active ? " on" : ""}${drop.over ? " drop-over" : ""}`}
        style={{ paddingLeft: 6 + depth * 14 }} {...drop.props}>
        <button className="twisty" onClick={() => setOpen(!open)} aria-label={open ? "Collapse" : "Expand"}
          style={{ visibility: kids.length ? "visible" : "hidden" }}>
          {open ? <ChevronDown /> : <ChevronRight />}
        </button>
        {renaming ? (
          <NameEditor value={f.name} autoFocus className="title-input side-input" label="Folder name"
            onSave={(name) => run(() => api.renameFolder(f.id, name))} onDone={() => setRenaming(false)} />
        ) : (
          <a className="side-link" href={`#/folder/${f.id}`}>
            {active ? <FolderOpen /> : <Folder />}
            <span className="side-label">{f.name}</span>
            <span className="side-count">{f.count}</span>
          </a>
        )}
        {!renaming && (
          <span className="row-actions">
            <button className="icon-btn" title="New subfolder" aria-label="New subfolder"
              onClick={() => (setOpen(true), props.setCreating({ kind: "folder", parent: f.id }))}>
              <FolderPlus />
            </button>
            <button className="icon-btn" title="Rename" aria-label="Rename folder" onClick={() => setRenaming(true)}>
              <Pencil />
            </button>
            <button className="icon-btn" title="Delete folder" aria-label="Delete folder"
              onClick={() => window.confirm(`Delete folder "${f.name}"? Its documents and subfolders move up a level.`)
                && run(async () => {
                  await api.deleteFolder(f.id);
                  if (active) location.hash = "#/";
                })}>
              <Trash2 />
            </button>
          </span>
        )}
      </div>
      {open && props.creating?.kind === "folder" && props.creating.parent === f.id && (
        <NewItem placeholder="Folder name" indent={depth + 1} onDone={() => props.setCreating(null)}
          onSave={(name) => run(() => api.createFolder(name, f.id))} />
      )}
      {open && <FolderTree {...props} parent={f.id} depth={depth + 1} />}
    </>
  );
}

function TagRow({ tag, current, colors, run }: {
  tag: Tag; current: LibraryView; colors: string[]; run: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [renaming, setRenaming] = useState(false);
  const [picking, setPicking] = useState(false);
  const active = current.kind === "tag" && current.id === tag.id;
  return (
    <>
      <div className={`side-item tag-row${active ? " on" : ""}`}>
        {renaming ? (
          <NameEditor value={tag.name} autoFocus className="title-input side-input" label="Tag name"
            onSave={(name) => run(() => api.updateTag(tag.id, { name }))} onDone={() => setRenaming(false)} />
        ) : (
          <a className="side-link" href={`#/tag/${tag.id}`}>
            <span className="tag-dot" style={{ "--tag": `var(--ctp-${tag.color})` } as CSSProperties} />
            <span className="side-label">{tag.name}</span>
            <span className="side-count">{tag.count ?? 0}</span>
          </a>
        )}
        {!renaming && (
          <span className="row-actions">
            <button className="icon-btn" title="Colour" aria-label="Change colour" onClick={() => setPicking(!picking)}>
              <Palette />
            </button>
            <button className="icon-btn" title="Rename" aria-label="Rename tag" onClick={() => setRenaming(true)}>
              <Pencil />
            </button>
            <button className="icon-btn" title="Delete tag" aria-label="Delete tag"
              onClick={() => window.confirm(`Delete tag "${tag.name}"? Documents keep everything else.`)
                && run(async () => {
                  await api.deleteTag(tag.id);
                  if (active) location.hash = "#/";
                })}>
              <Trash2 />
            </button>
          </span>
        )}
      </div>
      {picking && (
        <div className="tag-colors" role="radiogroup" aria-label={`Colour of ${tag.name}`}>
          {colors.map((c) => (
            <button key={c} role="radio" aria-checked={c === tag.color} aria-label={c} title={c}
              className={`swatch small${c === tag.color ? " on" : ""}`}
              style={{ "--sw": `var(--ctp-${c})` } as CSSProperties}
              onClick={() => run(() => api.updateTag(tag.id, { color: c })).then(() => setPicking(false))} />
          ))}
        </div>
      )}
    </>
  );
}

