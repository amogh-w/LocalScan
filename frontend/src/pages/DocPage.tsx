import { useCallback, useEffect, useRef, useState } from "react";
import { api, fileUrl, imageUrl, prepareImage, previewUrl, type Doc, type Filter, type Page, type Point } from "../api";
import CornerEditor from "../components/CornerEditor";
import { Downloads, StatusBadge } from "../components/common";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "enhanced", label: "Auto" },
  { id: "original", label: "Original" },
  { id: "grayscale", label: "Gray" },
  { id: "bw", label: "B&W" },
];
const FULL: Point[] = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
];

export default function DocPage({ id }: { id: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<"crop" | "preview">("crop");
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dragFrom = useRef<number | null>(null);
  // Page edits are sent one at a time, in order; only the newest reply updates the screen.
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const saveSeq = useRef(0);

  const run = useCallback(async <T,>(fn: () => Promise<T>) => {
    try {
      setError(null);
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    run(() => api.getDoc(id).then(setDoc));
  }, [id, run]);

  // Poll while the backend is working.
  const busy = doc?.status === "queued" || doc?.status === "processing";
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => api.getDoc(id).then(setDoc).catch(() => {}), 1500);
    return () => clearInterval(t);
  }, [busy, id]);

  useEffect(() => {
    if (doc && (!selected || !doc.pages.some((p) => p.id === selected))) setSelected(doc.pages[0]?.id ?? null);
  }, [doc, selected]);

  if (!doc) {
    return (
      <div className="screen">
        <Header title="…" />
        {error && <p className="error content">{error}</p>}
      </div>
    );
  }

  const page = doc.pages.find((p) => p.id === selected) ?? null;
  const index = page ? doc.pages.indexOf(page) : -1;

  const updatePage = (p: Page, patch: Partial<Pick<Page, "corners" | "rotation" | "filter">>) => {
    setDoc((d) => d && { ...d, status: d.status === "done" ? "draft" : d.status, pages: d.pages.map((q) => (q.id === p.id ? { ...q, ...patch } : q)) });
    const seq = ++saveSeq.current;
    saveQueue.current = saveQueue.current.then(() =>
      run(async () => {
        const saved = await api.patchPage(id, p.id, patch);
        if (seq === saveSeq.current) setDoc((d) => d && { ...d, pages: d.pages.map((q) => (q.id === p.id ? saved : q)) });
      }),
    );
    return saveQueue.current;
  };

  const translate = () =>
    run(async () => {
      await saveQueue.current; // never process before the last crop/filter change is stored
      setDoc(await api.process(id));
    });

  const addPhotos = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    setUploading({ done: 0, total: list.length });
    await run(async () => {
      let last: Doc | null = null;
      for (let i = 0; i < list.length; i++) {
        last = await api.uploadPages(id, [await prepareImage(list[i])]);
        setDoc(last);
        setUploading({ done: i + 1, total: list.length });
      }
      if (last) setSelected(last.pages[last.pages.length - list.length]?.id ?? null);
      setMode("crop");
    });
    setUploading(null);
  };

  const importPdf = async (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    setUploading({ done: 0, total: 1 });
    await run(async () => setDoc(await api.importPdf(id, f)));
    setUploading(null);
  };

  const move = async (from: number, to: number) => {
    if (to < 0 || to >= doc.pages.length || from === to) return;
    const order = doc.pages.map((p) => p.id);
    const [m] = order.splice(from, 1);
    order.splice(to, 0, m);
    await run(async () => setDoc(await api.reorder(id, order)));
  };

  const removePage = async (p: Page) => {
    if (!confirmDelete()) return;
    await run(async () => setDoc(await api.deletePage(id, p.id)));
  };

  const removeDoc = async () => {
    if (!window.confirm(`Delete "${doc.name}" and all its pages?`)) return;
    await run(async () => {
      await api.deleteDoc(id);
      location.hash = "#/";
    });
  };

  return (
    <div className="screen">
      <Header
        title={
          <input
            className="title-input"
            defaultValue={doc.name}
            onBlur={(e) => e.target.value !== doc.name && run(async () => setDoc(await api.renameDoc(id, e.target.value)))}
          />
        }
        right={
          <button className="icon-btn" onClick={removeDoc} disabled={busy} aria-label="Delete document">
            🗑
          </button>
        }
      />

      <main className="content">
        <div className="add-row">
          <label className={`btn primary${busy ? " disabled" : ""}`}>
            📷 Take photo
            <input type="file" accept="image/*" capture="environment" hidden disabled={busy}
              onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
          </label>
          <label className={`btn${busy ? " disabled" : ""}`}>
            🖼 Choose photos
            <input type="file" accept="image/*" multiple hidden disabled={busy}
              onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
          </label>
          <label className={`btn${busy ? " disabled" : ""}`}>
            📄 Import PDF
            <input type="file" accept="application/pdf" hidden disabled={busy}
              onChange={(e) => (importPdf(e.target.files), (e.target.value = ""))} />
          </label>
        </div>
        {uploading && (
          <p className="muted">
            Uploading {uploading.done}/{uploading.total}…
          </p>
        )}
        {error && <p className="error">{error}</p>}

        {doc.pages.length > 0 && (
          <div className="strip">
            {doc.pages.map((p, i) => (
              <button
                key={p.id}
                className={`thumb${p.id === selected ? " selected" : ""}`}
                onClick={() => setSelected(p.id)}
                draggable={!busy}
                onDragStart={() => (dragFrom.current = i)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => dragFrom.current !== null && move(dragFrom.current, i)}
              >
                <img src={previewUrl(id, p, 240)} alt={`Page ${i + 1}`} loading="lazy" />
                <span className="num">{i + 1}</span>
              </button>
            ))}
          </div>
        )}

        {page && (
          <section className="card editor">
            <div className="seg">
              <button className={mode === "crop" ? "on" : ""} onClick={() => setMode("crop")}>
                Crop
              </button>
              <button className={mode === "preview" ? "on" : ""} onClick={() => setMode("preview")}>
                Preview
              </button>
            </div>

            {mode === "crop" ? (
              <CornerEditor
                src={imageUrl(id, page.id)}
                aspect={page.width / page.height}
                corners={page.corners}
                onCommit={(corners) => !busy && updatePage(page, { corners })}
              />
            ) : (
              <img className="preview" src={previewUrl(id, page)} alt="Preview" />
            )}

            <div className="filters">
              {FILTERS.map((f) => (
                <button key={f.id} className={`pill${page.filter === f.id ? " on" : ""}`} disabled={busy}
                  onClick={() => updatePage(page, { filter: f.id })}>
                  {f.label}
                </button>
              ))}
            </div>

            <div className="tools">
              <button className="btn small" disabled={busy} onClick={() => updatePage(page, { rotation: (page.rotation + 270) % 360 })}>
                ⟲
              </button>
              <button className="btn small" disabled={busy} onClick={() => updatePage(page, { rotation: (page.rotation + 90) % 360 })}>
                ⟳
              </button>
              <button className="btn small" disabled={busy}
                onClick={() => run(async () => {
                  const saved = await api.autodetect(id, page.id);
                  setDoc((d) => d && { ...d, pages: d.pages.map((q) => (q.id === page.id ? saved : q)) });
                })}>
                Auto
              </button>
              <button className="btn small" disabled={busy} onClick={() => updatePage(page, { corners: FULL })}>
                Full
              </button>
              <button className="btn small" disabled={busy || index === 0} onClick={() => move(index, index - 1)}>
                ◀
              </button>
              <button className="btn small" disabled={busy || index === doc.pages.length - 1} onClick={() => move(index, index + 1)}>
                ▶
              </button>
              <button className="btn small danger" disabled={busy} onClick={() => removePage(page)}>
                Delete
              </button>
            </div>
          </section>
        )}
      </main>

      {doc.pages.length > 0 && (
        <footer className="action-bar">
          <div className="status-row">
            <StatusBadge doc={doc} />
            {doc.status === "error" && <span className="error small">{doc.error}</span>}
          </div>
          {busy && doc.progress && (
            <progress max={Math.max(1, doc.progress.total)} value={doc.progress.done} />
          )}
          {doc.status === "done" ? (
            <>
              <Downloads doc={doc} />
              <a className="btn small" href={fileUrl(id, "translated", true)} target="_blank">
                Open English PDF
              </a>
            </>
          ) : (
            <button className="btn primary big" disabled={busy} onClick={translate}>
              {busy ? "Working…" : `Translate ${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"}`}
            </button>
          )}
        </footer>
      )}
    </div>
  );
}

function confirmDelete() {
  return window.confirm("Delete this page?");
}

function Header({ title, right }: { title: React.ReactNode; right?: React.ReactNode }) {
  return (
    <header className="bar">
      <a className="icon-btn" href="#/" aria-label="Back">
        ←
      </a>
      <div className="bar-title">{title}</div>
      {right}
    </header>
  );
}
