import { useCallback, useEffect, useRef, useState } from "react";
import {
  Camera, ChevronLeft, ChevronRight, Ellipsis, Crop, Eye, FileUp, 
  Images, Languages, LayoutGrid, ListOrdered, LoaderCircle, 
  Check, FilePlus, Folder as FolderIcon, FolderInput, FolderOpen, Inbox, SlidersHorizontal, Split, Trash2, Undo2, X, type LucideIcon,
} from "lucide-react";
import { api, flattenFolders, imageUrl, prepareImage, previewUrl, translatedUrl, type Doc, type PageTranslation, type Folder, type Page, type Point } from "../api";
import ContextMenu, { type MenuItem } from "../components/ContextMenu";
import { Seg, ask } from "../components/kit";
import CornerEditor from "../components/CornerEditor";
import DocTitle from "../components/DocTitle";
import NameOptions from "../components/NameOptions";
import PageTools from "../components/PageTools";
import Organize from "../components/Organize";
import ProgressCard from "../components/ProgressCard";
import TranslatePanel from "../components/TranslatePanel";
import SortPages, { type SortResult } from "../components/SortPages";
import { AsyncButton } from "../components/common";

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
  const [pagesMenu, setPagesMenu] = useState<{ x: number; y: number } | null>(null); // Sort / Fix order
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
    if (sorted?.kind !== "split" || !await ask({
      title: `Remove these ${sorted.copied.length} pages from this scan?`,
      text: "They stay in the new documents, and the removed copies go to the trash.", ok: "Remove", icon: "trash-2", danger: true,
    })) return;
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
    if (!await ask({
      title: `Remove the saved translation of page ${doc!.pages.indexOf(p) + 1}?`, ok: "Remove", icon: "trash-2", danger: true,
    })) return;
    await run(async () => {
      setDoc(await api.clearPageTranslation(id, p.id));
      await loadStatus();
    });
  };

  const removeAllTranslations = async () => {
    if (!await ask({
      title: "Remove every saved translation?", text: "This also removes the PDFs. Your pages and photos stay.",
      ok: "Remove all", icon: "trash-2", danger: true,
    })) return;
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
    if (!await ask({ title: "Move this page to the trash?", ok: "Move to trash", icon: "trash-2", danger: true })) return;
    await run(async () => setDoc(await api.deletePage(id, p.id)));
  };

  const removeDoc = async () => {
    if (!await ask({
      title: `Move "${doc.name}" to the trash?`, text: "You can restore it from the trash for 30 days.",
      ok: "Move to trash", icon: "trash-2", danger: true,
    })) return;
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
    if (!await ask({
      title: `Move ${ids.length === 1 ? "this page" : `these ${ids.length} pages`} to the trash?`,
      ok: "Move to trash", icon: "trash-2", danger: true,
    })) return;
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
      <label className={`btn btn-tinted${busy ? " pointer-events-none opacity-40" : ""}`}>
        <Camera /> Take photo
        <input type="file" accept="image/*" capture="environment" hidden disabled={busy}
          onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
      </label>
      <label className={`btn btn-gray${busy ? " pointer-events-none opacity-40" : ""}`} title="Choose photos">
        <Images /> Photos
        <input type="file" accept="image/*" multiple hidden disabled={busy}
          onChange={(e) => (addPhotos(e.target.files), (e.target.value = ""))} />
      </label>
      <label className={`btn btn-gray${busy ? " pointer-events-none opacity-40" : ""}`} title="Import PDF">
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
          <AsyncButton className="btn btn-icon btn-plain" onClick={removeDoc} disabled={busy} ariaLabel="Move document to the trash"
            title="Move document to the trash" icon={<Trash2 />} />
        }
      />
      {error && <p className="error banner" role="alert">{error}</p>}

      <div className={`workspace show-${tab}`}>
        {/* Pages: thumbnail grid */}
        <aside className="panel pages-panel">
          <div className="panel-head">
            <h2>Pages</h2>
            {picked.size > 0 ? (
              <span className="picked-bar">
                <span className="small">{picked.size} selected</span>
                <button className="btn btn-gray btn-sm" disabled={busy} aria-haspopup="menu"
                  onClick={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    openMenu(r.left, r.bottom + 4, doc.pages.filter((q) => picked.has(q.id)).map((q) => q.id));
                  }}>
                  Actions
                </button>
                <button className="btn btn-icon btn-sm btn-plain" onClick={clearPicked} aria-label="Clear selection" title="Clear selection (Esc)"><X /></button>
              </span>
            ) : (
              <span className="picked-bar">
                <span className="muted small">{doc.pages.length}</span>
                {doc.pages.length >= 2 && (
                  <button className="btn btn-icon btn-sm btn-plain" disabled={busy} aria-haspopup="menu" aria-label="More page actions"
                    title="Sort the pages with AI, or fix their order"
                    onClick={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setPagesMenu({ x: r.left, y: r.bottom + 4 });
                    }}>
                    <Ellipsis />
                  </button>
                )}
              </span>
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
                  className={`page-thumb${p.id === selected ? " selected" : ""}${picked.has(p.id) ? " picked" : ""}`}
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
              <Seg label="View" value={mode} onChange={setMode} options={[
                { id: "crop", label: <><Crop /> Crop</> },
                { id: "preview", label: <><Eye /> Preview</> },
                { id: "translated", label: <><Languages /> Translated</> },
              ]} />
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
                          <AsyncButton className="btn btn-filled" icon={<Languages />} onClick={() => translateThisPage(page)}>
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
              {mode !== "translated" && (
                <PageTools filter={page.filter} index={index} count={doc.pages.length} busy={!!busy}
                  onFilter={(filter) => updatePage(page, { filter })}
                  onDetect={() => run(async () => {
                    const saved = await api.autodetect(id, page.id);
                    setDoc((d) => d && { ...d, pages: d.pages.map((q) => (q.id === page.id ? saved : q)) });
                  })}
                  onFull={() => updatePage(page, { corners: FULL })}
                  onRotate={(turns) => updatePage(page, { rotation: (page.rotation + 360 + 90 * turns) % 360 })}
                  onMove={(to) => move(index, to)}
                  onDelete={() => removePage(page)} />
              )}
              <nav className="pager" aria-label="Page navigation">
                <button className="btn btn-icon btn-sm btn-gray" disabled={index <= 0} onClick={() => goTo(index - 1)}
                  aria-label="Previous page" title="Previous page">
                  <ChevronLeft />
                </button>
                <span className="pager-label">
                  Page <b>{index + 1}</b> of {doc.pages.length}
                </span>
                <button className="btn btn-icon btn-sm btn-gray" disabled={index >= doc.pages.length - 1} onClick={() => goTo(index + 1)}
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
          {doc.pages.length > 0 && (
            <TranslatePanel doc={doc} page={page} index={index} tstat={tstat} busy={!!busy} onGoTo={goTo}
              onTranslateAll={translateAll} onTranslatePage={translateThisPage} onRemovePage={removePageTranslation}
              onRemoveAll={removeAllTranslations} />
          )}
          </div>
        </aside>
      </div>

      {sorting && <SortPages doc={doc} split={sorting === "split"} onClose={() => setSorting(null)} onApplied={applied} />}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.ids)} onClose={() => setMenu(null)} />}
      {pagesMenu && (
        <ContextMenu x={pagesMenu.x} y={pagesMenu.y} onClose={() => setPagesMenu(null)} items={[
          { label: "Sort with AI", icon: <Split />, onSelect: () => setSorting("split") },
          { label: "Fix order", icon: <ListOrdered />, onSelect: () => setSorting("order") },
        ]} />
      )}
      {moved && (
        <div className="toasts"><div className="toast" role="status">
          <span>Moved {moved.ids.length === 1 ? "1 page" : `${moved.ids.length} pages`} to {moved.where === "a new scan" ? "a new scan" : moved.where}.</span>
          <a className="btn btn-gray btn-sm" href={`#/doc/${moved.doc.id}`}>Open</a>
          <AsyncButton onClick={undoMove} icon={<Undo2 />}>Undo</AsyncButton>
          <button className="btn btn-icon btn-sm btn-plain" onClick={() => setMoved(null)} aria-label="Dismiss" title="Dismiss"><X /></button>
        </div></div>
      )}
      {sorted && !moved && (
        <div className="toasts"><div className="toast" role="status">
          <span>
            {sorted.kind === "split"
              ? `Created ${sorted.docs.length} document${sorted.docs.length === 1 ? "" : "s"}. ${sorted.removed ? "The pages were removed from this scan." : "This scan is unchanged."}`
              : "Page order updated."}
          </span>
          {sorted.kind === "split" && <a className="btn btn-gray btn-sm" href="#/">Library</a>}
          {sorted.kind === "split" && !sorted.removed && (
            <AsyncButton onClick={removeCopied} icon={<Trash2 />}>Remove from this scan</AsyncButton>
          )}
          {!(sorted.kind === "split" && sorted.removed) && (
            <AsyncButton onClick={undoSort} icon={<Undo2 />}>Undo</AsyncButton>
          )}
          <button className="btn btn-icon btn-sm btn-plain" onClick={() => setSorted(null)} aria-label="Dismiss" title="Dismiss"><X /></button>
        </div></div>
      )}

      <nav className="tabbar doc-tabbar" aria-label="Sections">
        {TABS.map((t) => (
          <button key={t.id} className="tab" onClick={() => setTab(t.id)} aria-selected={tab === t.id}
            aria-current={tab === t.id ? "page" : undefined}>
            <t.icon className="size-6" />
            <span>{t.label}</span>
            {t.id === "options" && (busy || doc.status === "done") && <span className={`dot ${doc.status}`} />}
          </button>
        ))}
      </nav>
    </div>
  );
}

function Header({ title, right }: { title: React.ReactNode; right?: React.ReactNode }) {
  return (
    <header className="app-bar">
      <a className="btn btn-icon btn-plain" href="#/" aria-label="Back" title="Back">
        <ChevronLeft />
      </a>
      <div className="bar-title">{title}</div>
      {right}
    </header>
  );
}
