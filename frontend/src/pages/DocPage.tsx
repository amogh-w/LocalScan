import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft, ArrowRight, Camera, ChevronLeft, ChevronRight, Contrast, Crop, ExternalLink, Eye, FileUp, Image,
  Images, Languages, LayoutGrid, LoaderCircle, Maximize, Palette, RotateCcw, RotateCw, ScanSearch, ScanText,
  SlidersHorizontal, Sparkles, Trash2, type LucideIcon,
} from "lucide-react";
import { api, fileUrl, imageUrl, prepareImage, previewUrl, type Doc, type Filter, type Page, type Point } from "../api";
import CornerEditor from "../components/CornerEditor";
import DocTitle from "../components/DocTitle";
import NameOptions from "../components/NameOptions";
import { Downloads, StatusBadge } from "../components/common";

const FILTERS: { id: Filter; label: string; icon: LucideIcon }[] = [
  { id: "enhanced", label: "Auto", icon: Sparkles },
  { id: "original", label: "Original", icon: Image },
  { id: "grayscale", label: "Gray", icon: Contrast },
  { id: "bw", label: "B&W", icon: ScanText },
];
const FULL: Point[] = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
];

// On narrow screens the three panels become tabs; on wide screens all three show side by side.
type Tab = "pages" | "page" | "options";
const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "pages", label: "Pages", icon: LayoutGrid },
  { id: "page", label: "Page", icon: Crop },
  { id: "options", label: "Options", icon: SlidersHorizontal },
];

export default function DocPage({ id }: { id: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<"crop" | "preview">("crop");
  const [tab, setTab] = useState<Tab>("pages");
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

  const openPage = (pageId: string) => {
    setSelected(pageId);
    setTab("page");
  };
  const goTo = (i: number) => doc.pages[i] && setSelected(doc.pages[i].id);

  const addButtons = (
    <div className="add-grid">
      <label className={`btn primary${busy ? " disabled" : ""}`}>
        <Camera /> Take photo
        <input type="file" accept="image/*" capture="environment" hidden disabled={busy}
          onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
      </label>
      <label className={`btn${busy ? " disabled" : ""}`} title="Choose photos">
        <Images /> Photos
        <input type="file" accept="image/*" multiple hidden disabled={busy}
          onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
      </label>
      <label className={`btn${busy ? " disabled" : ""}`} title="Import PDF">
        <FileUp /> PDF
        <input type="file" accept="application/pdf" hidden disabled={busy}
          onChange={(e) => (importPdf(e.target.files), (e.target.value = ""))} />
      </label>
    </div>
  );

  return (
    <div className="screen doc-screen">
      <Header
        title={<DocTitle doc={doc} onChange={setDoc} onError={setError} />}
        right={
          <button className="icon-btn" onClick={removeDoc} disabled={busy} aria-label="Delete document" title="Delete document">
            <Trash2 />
          </button>
        }
      />
      {error && <p className="error banner">{error}</p>}

      <div className={`workspace show-${tab}`}>
        {/* Pages: thumbnail grid */}
        <aside className="panel pages-panel">
          <div className="panel-head">
            <h2>Pages</h2>
            <span className="muted small">{doc.pages.length}</span>
          </div>
          {addButtons}
          {uploading && (
            <p className="muted small with-icon">
              <LoaderCircle className="spin" /> Uploading {uploading.done}/{uploading.total}…
            </p>
          )}
          {doc.pages.length === 0 ? (
            <div className="empty-state">
              <Camera />
              <p>Take a photo of each page, or choose photos you already have.</p>
            </div>
          ) : (
            <div className="page-grid">
              {doc.pages.map((p, i) => (
                <button
                  key={p.id}
                  className={`thumb${p.id === selected ? " selected" : ""}`}
                  onClick={() => openPage(p.id)}
                  draggable={!busy}
                  onDragStart={() => (dragFrom.current = i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => dragFrom.current !== null && move(dragFrom.current, i)}
                  aria-label={`Page ${i + 1}`}
                >
                  <img src={previewUrl(id, p, 300)} alt="" loading="lazy" />
                  <span className="num">{i + 1}</span>
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* Page: the selected page, large, with page navigation underneath */}
        <main className="panel page-panel">
          {page ? (
            <>
              <div className="seg">
                <button className={mode === "crop" ? "on" : ""} onClick={() => setMode("crop")}>
                  <Crop /> Crop
                </button>
                <button className={mode === "preview" ? "on" : ""} onClick={() => setMode("preview")}>
                  <Eye /> Preview
                </button>
              </div>
              <div className="stage">
                {mode === "crop" ? (
                  <CornerEditor
                    key={page.id}
                    src={imageUrl(id, page.id)}
                    aspect={page.width / page.height}
                    corners={page.corners}
                    onCommit={(corners) => !busy && updatePage(page, { corners })}
                  />
                ) : (
                  <img className="preview" src={previewUrl(id, page)} alt="Preview" />
                )}
              </div>
              <nav className="pager" aria-label="Page navigation">
                <button className="btn small" disabled={index <= 0} onClick={() => goTo(index - 1)}
                  aria-label="Previous page" title="Previous page">
                  <ChevronLeft />
                </button>
                <span className="pager-label">
                  Page <b>{index + 1}</b> of {doc.pages.length}
                </span>
                <button className="btn small" disabled={index >= doc.pages.length - 1} onClick={() => goTo(index + 1)}
                  aria-label="Next page" title="Next page">
                  <ChevronRight />
                </button>
              </nav>
            </>
          ) : (
            <div className="empty-state">
              <Crop />
              <p>Add a page to start cropping.</p>
            </div>
          )}
        </main>

        {/* Options: color, crop, other actions, then translate/export */}
        <aside className="panel options-panel">
          <NameOptions doc={doc} onChange={setDoc} onError={setError} />
          {page && (
            <>
              <section className="opt-group">
                <h3 className="with-icon"><Palette /> Color</h3>
                <div className="filter-grid">
                  {FILTERS.map((f) => (
                    <button key={f.id} className={`pill${page.filter === f.id ? " on" : ""}`} disabled={busy}
                      onClick={() => updatePage(page, { filter: f.id })} aria-pressed={page.filter === f.id}>
                      <f.icon /> {f.label}
                    </button>
                  ))}
                </div>
              </section>

              <section className="opt-group">
                <h3 className="with-icon"><Crop /> Crop</h3>
                <div className="tool-grid">
                  <button className="btn small" disabled={busy} title="Detect the page edges again"
                    onClick={() => run(async () => {
                      const saved = await api.autodetect(id, page.id);
                      setDoc((d) => d && { ...d, pages: d.pages.map((q) => (q.id === page.id ? saved : q)) });
                    })}>
                    <ScanSearch /> Detect
                  </button>
                  <button className="btn small" disabled={busy} title="Use the whole photo"
                    onClick={() => updatePage(page, { corners: FULL })}>
                    <Maximize /> Full
                  </button>
                  <button className="btn small" disabled={busy} title="Rotate left"
                    onClick={() => updatePage(page, { rotation: (page.rotation + 270) % 360 })}>
                    <RotateCcw /> Left
                  </button>
                  <button className="btn small" disabled={busy} title="Rotate right"
                    onClick={() => updatePage(page, { rotation: (page.rotation + 90) % 360 })}>
                    <RotateCw /> Right
                  </button>
                </div>
              </section>

              <section className="opt-group">
                <h3 className="with-icon"><SlidersHorizontal /> Page</h3>
                <div className="tool-grid">
                  <button className="btn small" disabled={busy || index === 0} onClick={() => move(index, index - 1)}
                    title="Move page earlier">
                    <ArrowLeft /> Earlier
                  </button>
                  <button className="btn small" disabled={busy || index === doc.pages.length - 1}
                    onClick={() => move(index, index + 1)} title="Move page later">
                    <ArrowRight /> Later
                  </button>
                  <button className="btn small danger span-2" disabled={busy} onClick={() => removePage(page)}>
                    <Trash2 /> Delete page
                  </button>
                </div>
              </section>
            </>
          )}

          {doc.pages.length > 0 && (
            <section className="opt-group export">
              <h3 className="with-icon"><Languages /> Translate</h3>
              <div className="status-row">
                <StatusBadge doc={doc} />
                {doc.status === "error" && <span className="error small">{doc.error}</span>}
              </div>
              {busy && doc.progress && <progress max={Math.max(1, doc.progress.total)} value={doc.progress.done} />}
              {doc.status === "done" ? (
                <>
                  <a className="btn primary" href={fileUrl(id, "translated", true)} target="_blank">
                    <ExternalLink /> Open English PDF
                  </a>
                  <Downloads doc={doc} compact />
                </>
              ) : (
                <button className="btn primary big" disabled={busy} onClick={translate}>
                  {busy ? <LoaderCircle className="spin" /> : <Languages />}
                  {busy ? "Working…" : `Translate ${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"}`}
                </button>
              )}
            </section>
          )}
        </aside>
      </div>

      <nav className="tabbar" aria-label="Sections">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}>
            <t.icon />
            <span>{t.label}</span>
            {t.id === "options" && (busy || doc.status === "done") && <span className={`dot ${doc.status}`} />}
          </button>
        ))}
      </nav>
    </div>
  );
}

function confirmDelete() {
  return window.confirm("Delete this page?");
}

function Header({ title, right }: { title: React.ReactNode; right?: React.ReactNode }) {
  return (
    <header className="bar">
      <a className="icon-btn" href="#/" aria-label="Back" title="Back">
        <ChevronLeft />
      </a>
      <div className="bar-title">{title}</div>
      {right}
    </header>
  );
}
