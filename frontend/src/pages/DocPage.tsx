import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft, ArrowRight, Camera, ChevronLeft, ChevronRight, Contrast, Crop, Eye, FileUp, Image,
  Images, Languages, LayoutGrid, ListOrdered, LoaderCircle, Maximize, Palette, RotateCcw, RotateCw, ScanSearch, ScanText,
  Check, FilePlus, Folder as FolderIcon, RefreshCw, FolderInput, FolderOpen, Inbox, SlidersHorizontal, Sparkles, Split, Trash2, Undo2, X, type LucideIcon,
} from "lucide-react";
import { api, flattenFolders, imageUrl, prepareImage, previewUrl, translatedUrl, type Doc, type PageTranslation, type Filter, type Folder, type Page, type Point } from "../api";
import ContextMenu, { type MenuItem } from "../components/ContextMenu";
import CornerEditor from "../components/CornerEditor";
import DocTitle from "../components/DocTitle";
import NameOptions from "../components/NameOptions";
import Organize from "../components/Organize";
import ProgressCard from "../components/ProgressCard";
import SortPages, { type SortResult } from "../components/SortPages";
import { AsyncButton, PdfLinks, StatusBadge } from "../components/common";

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
  const [mode, setMode] = useState<"crop" | "preview" | "translated">("crop");
  const [tstat, setTstat] = useState<Record<string, PageTranslation>>({}); // saved translation per page
  const [tab, setTab] = useState<Tab>("pages");
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sorting, setSorting] = useState<"split" | "order" | null>(null);
  const [sorted, setSorted] = useState<SortResult | null>(null);
  // Several pages can be picked (Ctrl/Cmd-click, Shift-click); the right-click menu acts on the picked pages.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const anchor = useRef<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; ids: string[] } | null>(null);
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [moved, setMoved] = useState<{ doc: Doc; ids: string[]; positions: number[]; where: string } | null>(null);
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

  // Escape clears the picked pages (a hook, so it must stay above the early return below).
  useEffect(() => {
    if (!picked.size) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setPicked(new Set());
      anchor.current = null;
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [picked.size]);

  // Poll while the backend is working.
  const busy = doc?.status === "queued" || doc?.status === "processing";
  const loadStatus = useCallback(() => api.translationStatus(id).then(setTstat).catch(() => {}), [id]);
  useEffect(() => {
    if (!busy) loadStatus(); // after every job, and on opening the document
  }, [busy, loadStatus, doc?.pages.length]);
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => api.getDoc(id).then(setDoc).catch(() => {}), 1500);
    return () => clearInterval(t);
  }, [busy, id]);

  useEffect(() => {
    if (doc && (!selected || !doc.pages.some((p) => p.id === selected))) setSelected(doc.pages[0]?.id ?? null);
  }, [doc, selected]);

  const applied = (result: SortResult) => {
    setSorting(null);
    setSorted(result);
    setMoved(null);
    if (result.kind === "reorder") setDoc(result.doc);
  };

  const undoSort = () => run(async () => {
    if (!sorted) return;
    if (sorted.kind === "split") await api.bulk(sorted.docs.map((d) => d.id), "delete");
    else setDoc(await api.reorder(id, sorted.previous));
    setSorted(null);
  });

  const removeCopied = () => run(async () => {
    if (sorted?.kind !== "split" || !window.confirm(`Remove these ${sorted.copied.length} pages from this scan? They stay in the new documents, and the removed copies go to the trash.`)) return;
    setDoc(await api.removePages(id, sorted.copied));
    setSorted({ ...sorted, removed: true });
  });

  if (!doc) {
    return (
      <div className="screen">
        <Header title="…" />
        {error && <p className="error content">{error}</p>}
      </div>
    );
  }

  const page = doc.pages.find((p) => p.id === selected) ?? null;
  const stat = page ? tstat[page.id] : undefined;
  const translatedPage = (s?: PageTranslation) => !!s && s.read && s.total > 0 && s.done === s.total;
  // A page is done when its text was read and every paragraph has a translation (a page with no text is done).
  const pageDone = (s?: PageTranslation) => !!s && s.read && s.done === s.total;
  const doneCount = doc.pages.filter((p) => pageDone(tstat[p.id])).length;
  const remaining = doc.pages.length - doneCount;
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

  /** Translate every page and build the PDFs; again = ignore the saved translations and translate it all anew. */
  const translateAll = (again = false) =>
    run(async () => {
      await saveQueue.current; // never process before the last crop/filter change is stored
      setDoc(await api.process(id, again));
    });

  const translateThisPage = (p: Page, again = false) =>
    run(async () => {
      await saveQueue.current;
      setDoc(await api.translatePage(id, p.id, again));
      setMode("translated");
    });

  const removePageTranslation = async (p: Page) => {
    if (!window.confirm(`Remove the saved translation of page ${doc!.pages.indexOf(p) + 1}?`)) return;
    await run(async () => {
      setDoc(await api.clearPageTranslation(id, p.id));
      await loadStatus();
    });
  };

  const removeAllTranslations = async () => {
    if (!window.confirm("Remove every saved translation of this document and its PDFs? Your pages and photos stay.")) return;
    await run(async () => {
      setDoc(await api.clearTranslations(id));
      await loadStatus();
    });
  };

  const addPhotos = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    setUploading({ done: 0, total: list.length });
    await run(async () => {
      const cfg = await api.uploadConfig().catch(() => undefined); // the size limit chosen in Settings
      let last: Doc | null = null;
      for (let i = 0; i < list.length; i++) {
        last = await api.uploadPages(id, [await prepareImage(list[i], cfg)]);
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
    if (!window.confirm(`Move "${doc.name}" to the trash?`)) return;
    await run(async () => {
      await api.deleteDoc(id);
      location.hash = "#/";
    });
  };

  // --- picking pages and the right-click menu ---------------------------------------------------
  const clearPicked = () => {
    setPicked(new Set());
    anchor.current = null;
  };

  const clickThumb = (e: React.MouseEvent, p: Page) => {
    const from = anchor.current ?? selected; // a range starts at the last clicked page, else the open one
    if (e.shiftKey && from) {
      const ids = doc.pages.map((q) => q.id);
      const [a, b] = [ids.indexOf(from), ids.indexOf(p.id)].sort((m, n) => m - n);
      setPicked(new Set(ids.slice(a, b + 1)));
    } else if (e.ctrlKey || e.metaKey) {
      const next = new Set(picked);
      if (next.has(p.id)) next.delete(p.id);
      else next.add(p.id);
      setPicked(next);
      anchor.current = p.id;
    } else {
      clearPicked();
      anchor.current = p.id;
      openPage(p.id);
    }
  };

  /** The pages an action applies to, in document order: the picked pages, or just the one under the pointer. */
  const targets = (p: Page) => {
    const chosen = picked.has(p.id) ? picked : new Set([p.id]);
    if (!picked.has(p.id)) {
      setPicked(chosen);
      anchor.current = p.id;
    }
    return doc.pages.filter((q) => chosen.has(q.id)).map((q) => q.id);
  };

  const openMenu = (x: number, y: number, ids: string[]) => {
    if (busy) return;
    if (!folders) api.listFolders().then(setFolders).catch(() => setFolders([]));
    setMenu({ x, y, ids });
  };

  const movePagesTo = (ids: string[], folder: string | null | undefined, where: string) =>
    run(async () => {
      await saveQueue.current;
      const out = await api.movePages(id, ids, folder);
      setDoc(out.source);
      clearPicked();
      setSorted(null);
      setMoved({ doc: out.document, ids, positions: out.positions, where });
    });

  const undoMove = () => run(async () => {
    if (!moved) return;
    setDoc(await api.returnPages(id, moved.ids, moved.doc.id, moved.positions));
    setMoved(null);
  });

  const deletePages = async (ids: string[]) => {
    if (!window.confirm(`Move ${ids.length === 1 ? "this page" : `these ${ids.length} pages`} to the trash?`)) return;
    await run(async () => {
      setDoc(await api.removePages(id, ids));
      clearPicked();
    });
  };

  const menuItems = (ids: string[]): MenuItem[] => {
    const many = ids.length > 1;
    const noun = many ? `${ids.length} pages` : "page";
    const tree = flattenFolders(folders ?? []);
    return [
      { label: `New scan from ${noun}`, icon: <FilePlus />, onSelect: () => movePagesTo(ids, undefined, "a new scan") },
      {
        label: "Move to folder", icon: <FolderInput />,
        children: [
          { label: "Same folder as this document", icon: <FolderOpen />, onSelect: () => movePagesTo(ids, undefined, "this document's folder") },
          { label: "Unfiled", icon: <Inbox />, onSelect: () => movePagesTo(ids, null, "Unfiled") },
          ...tree.map((f) => ({ label: f.name, depth: f.depth, icon: <FolderIcon />, onSelect: () => movePagesTo(ids, f.id, f.name) })),
          ...(folders && !tree.length ? [{ label: "No folders yet", disabled: true }] : []),
        ],
      },
      { label: `Delete ${noun}`, icon: <Trash2 />, danger: true, onSelect: () => deletePages(ids) },
    ];
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
          <AsyncButton className="icon-btn" onClick={removeDoc} disabled={busy} ariaLabel="Move document to the trash"
            title="Move document to the trash" icon={<Trash2 />} />
        }
      />
      {error && <p className="error banner">{error}</p>}

      <div className={`workspace show-${tab}`}>
        {/* Pages: thumbnail grid */}
        <aside className="panel pages-panel">
          <div className="panel-head">
            <h2>Pages</h2>
            {picked.size > 0 ? (
              <span className="picked-bar">
                <span className="small">{picked.size} selected</span>
                <button className="btn small" disabled={busy} aria-haspopup="menu"
                  onClick={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    openMenu(r.left, r.bottom + 4, doc.pages.filter((q) => picked.has(q.id)).map((q) => q.id));
                  }}>
                  Actions
                </button>
                <button className="icon-btn" onClick={clearPicked} aria-label="Clear selection" title="Clear selection (Esc)"><X /></button>
              </span>
            ) : (
              <span className="muted small">{doc.pages.length}</span>
            )}
          </div>
          {addButtons}
          {uploading && (
            <ProgressCard title="Uploading photos" detail={`${uploading.done} of ${uploading.total} done`}
              percent={Math.round(100 * uploading.done / Math.max(1, uploading.total))} />
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
                  className={`thumb${p.id === selected ? " selected" : ""}${picked.has(p.id) ? " picked" : ""}`}
                  onClick={(e) => clickThumb(e, p)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    openMenu(e.clientX, e.clientY, targets(p));
                  }}
                  aria-pressed={picked.has(p.id) || undefined}
                  draggable={!busy}
                  onDragStart={() => (dragFrom.current = i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => dragFrom.current !== null && move(dragFrom.current, i)}
                  aria-label={`Page ${i + 1}`}
                >
                  <img src={previewUrl(id, p, 300)} alt="" loading="lazy" />
                  <span className="num">{i + 1}</span>
                  {translatedPage(tstat[p.id]) && <span className="tick" title="Translated"><Check /></span>}
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
                <button className={mode === "translated" ? "on" : ""} onClick={() => setMode("translated")}>
                  <Languages /> Translated
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
                ) : mode === "translated" ? (
                  stat && stat.done > 0 ? (
                    <img className="preview" src={translatedUrl(id, page.id, stat.done)} alt="Translated page" />
                  ) : (
                    <div className="translated-empty">
                      <div className="te-icon">{busy ? <LoaderCircle className="spin" /> : <Languages />}</div>
                      {busy ? (
                        <>
                          <h3>Translating…</h3>
                          <p>You can follow the progress in the Translate box on the right.</p>
                        </>
                      ) : stat?.read && stat.total === 0 ? (
                        <>
                          <h3>Nothing to translate</h3>
                          <p>This page has no text, only numbers or codes, so it looks the same in every language.</p>
                        </>
                      ) : (
                        <>
                          <h3>Page {index + 1} is not translated yet</h3>
                          <p>Translate just this page to see the English version here. The other pages are left alone.</p>
                          <AsyncButton className="btn primary" icon={<Languages />} onClick={() => translateThisPage(page)}>
                            Translate this page
                          </AsyncButton>
                        </>
                      )}
                    </div>
                  )
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
          <div className="options-panel-grid">
          <NameOptions doc={doc} onChange={setDoc} onError={setError} />
          <Organize doc={doc} onChange={setDoc} onError={setError} />
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
                  <AsyncButton disabled={busy} title="Detect the page edges again" icon={<ScanSearch />}
                    onClick={() => run(async () => {
                      const saved = await api.autodetect(id, page.id);
                      setDoc((d) => d && { ...d, pages: d.pages.map((q) => (q.id === page.id ? saved : q)) });
                    })}>
                    Detect
                  </AsyncButton>
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
                  {doc.pages.length >= 2 && (
                    <>
                      <button className="btn small" disabled={busy} onClick={() => setSorting("split")}
                        title="Find the documents in this scan and put their pages in order">
                        <Split /> Sort
                      </button>
                      <button className="btn small" disabled={busy} onClick={() => setSorting("order")}
                        title="Keep one document, fix the page order">
                        <ListOrdered /> Fix order
                      </button>
                    </>
                  )}
                  <AsyncButton className="btn small danger span-2" disabled={busy} onClick={() => removePage(page)} icon={<Trash2 />}>
                    Delete page
                  </AsyncButton>
                </div>
              </section>
            </>
          )}

          {doc.pages.length > 0 && (
            <section className="opt-group export wide">
              <h3 className="with-icon"><Languages /> Translate</h3>
              <div className="status-row">
                <StatusBadge doc={doc} />
                {doc.status === "error" && <span className="error small">{doc.error}</span>}
              </div>
              {busy && (doc.progress ? (
                <ProgressCard title={doc.progress.step} detail={doc.progress.detail} percent={doc.progress.percent}
                  step={doc.progress.stage ? `Step ${doc.progress.stage} of ${doc.progress.stages}` : undefined}
                  elapsed={doc.progress.elapsed} />
              ) : (
                <ProgressCard title={doc.status === "queued" ? "Waiting for its turn" : "Starting"}
                  detail={doc.status === "queued" ? "Another document is being processed first" : undefined} />
              ))}
              {page && (
                <div className="translate-part">
                  <h4>
                    This page <span className="muted">(page {index + 1})</span>
                    <span className={`state-chip${translatedPage(stat) ? " ok" : ""}`}>
                      {translatedPage(stat) ? "Translated" : stat && stat.done > 0 ? "Partly translated" : "Not translated"}
                    </span>
                  </h4>
                  <div className="tool-grid">
                    <AsyncButton className={`btn small${translatedPage(stat) ? "" : " primary"}`} disabled={busy}
                      icon={translatedPage(stat) ? <RefreshCw /> : <Languages />}
                      onClick={() => translateThisPage(page, translatedPage(stat))}
                      title={translatedPage(stat) ? "Translate this page again" : "Translate only this page"}>
                      {translatedPage(stat) ? "Translate again" : "Translate page"}
                    </AsyncButton>
                    <AsyncButton className="btn small danger" disabled={busy || !stat?.done} icon={<Trash2 />}
                      onClick={() => removePageTranslation(page)} title="Remove the saved translation of this page">
                      Remove
                    </AsyncButton>
                  </div>
                </div>
              )}
              <div className="translate-part">
                <h4>
                  All pages <span className="muted">({doneCount} of {doc.pages.length} translated)</span>
                </h4>
                <div className="page-dots" role="group" aria-label="Translated pages">
                  {doc.pages.map((p, i) => (
                    <button key={p.id} type="button" onClick={() => goTo(i)}
                      className={`page-dot${pageDone(tstat[p.id]) ? " on" : ""}${p.id === page?.id ? " cur" : ""}`}
                      title={`Page ${i + 1}: ${pageDone(tstat[p.id]) ? "translated" : "not translated yet"}`}>
                      {i + 1}
                    </button>
                  ))}
                </div>
                <div className="tool-grid">
                  {(remaining > 0 || doc.status !== "done") && (
                    <AsyncButton className="btn small primary span-2" disabled={busy} icon={<Languages />}
                      onClick={() => translateAll(false)}
                      title="Translate the pages that are not done yet, then make the three PDFs">
                      {remaining === 0 ? "Make the PDFs"
                        : doneCount === 0 ? `Translate all ${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"}`
                        : `Translate remaining (${remaining})`}
                    </AsyncButton>
                  )}
                  <AsyncButton className="btn small" disabled={busy} icon={<RefreshCw />}
                    onClick={() => translateAll(true)} title="Ignore the saved translations and translate every page again">
                    Translate all again
                  </AsyncButton>
                  <AsyncButton className="btn small danger" disabled={busy} icon={<Trash2 />}
                    onClick={removeAllTranslations} title="Remove every saved translation and the PDFs">
                    Remove all
                  </AsyncButton>
                </div>
              </div>
              {doc.status === "done" && <PdfLinks doc={doc} layout="stack" />}
            </section>
          )}
          </div>
        </aside>
      </div>

      {sorting && <SortPages doc={doc} split={sorting === "split"} onClose={() => setSorting(null)} onApplied={applied} />}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.ids)} onClose={() => setMenu(null)} />}
      {moved && (
        <div className="toast" role="status">
          <span>Moved {moved.ids.length === 1 ? "1 page" : `${moved.ids.length} pages`} to {moved.where === "a new scan" ? "a new scan" : moved.where}.</span>
          <a className="btn small" href={`#/doc/${moved.doc.id}`}>Open</a>
          <AsyncButton onClick={undoMove} icon={<Undo2 />}>Undo</AsyncButton>
          <button className="icon-btn" onClick={() => setMoved(null)} aria-label="Dismiss" title="Dismiss"><X /></button>
        </div>
      )}
      {sorted && !moved && (
        <div className="toast" role="status">
          <span>
            {sorted.kind === "split"
              ? `Created ${sorted.docs.length} document${sorted.docs.length === 1 ? "" : "s"}. ${sorted.removed ? "The pages were removed from this scan." : "This scan is unchanged."}`
              : "Page order updated."}
          </span>
          {sorted.kind === "split" && <a className="btn small" href="#/">Library</a>}
          {sorted.kind === "split" && !sorted.removed && (
            <AsyncButton onClick={removeCopied} icon={<Trash2 />}>Remove from this scan</AsyncButton>
          )}
          {!(sorted.kind === "split" && sorted.removed) && (
            <AsyncButton onClick={undoSort} icon={<Undo2 />}>Undo</AsyncButton>
          )}
          <button className="icon-btn" onClick={() => setSorted(null)} aria-label="Dismiss" title="Dismiss"><X /></button>
        </div>
      )}

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
  return window.confirm("Move this page to the trash?");
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
