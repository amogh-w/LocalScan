import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Inbox, ListOrdered, LoaderCircle, Sparkles, TriangleAlert, X } from "lucide-react";
import ProgressCard from "./ProgressCard";
import { api, previewUrl, type Confidence, type Doc, type SortProposal } from "../api";

export type SortResult =
  | { kind: "split"; docs: Doc[]; copied: string[]; removed?: boolean }
  | { kind: "reorder"; doc: Doc; previous: string[] };

interface Item { id: string; position: number; why?: string }
interface Row {
  key: number;
  name: string;
  edited: boolean;
  confidence: Confidence;
  reason: string;
  fromMarkers: boolean;
  items: Item[];
}

const LABEL: Record<Confidence, string> = { high: "High", medium: "Medium", low: "Low" };
const TRAY = -1;

function rowsFrom(p: SortProposal): { rows: Row[]; tray: Item[] } {
  return {
    rows: p.groups.map((g, key) => ({
      key, name: g.name, edited: false, confidence: g.confidence, reason: g.reason, fromMarkers: g.order_from_markers,
      items: g.page_ids.map((id, i) => ({ id, position: g.positions[i] })),
    })),
    tray: p.unplaced.map((u) => ({ id: u.page_id, position: u.position, why: u.why })),
  };
}

/**
 * Review sheet for "sort pages with AI". The model only proposes; nothing changes until Apply.
 * split=true creates new documents (copies of the pages); split=false reorders this document in place.
 */
export default function SortPages({ doc, split, onClose, onApplied }: {
  doc: Doc; split: boolean; onClose: () => void; onApplied: (result: SortResult) => void;
}) {
  const [proposal, setProposal] = useState<SortProposal | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [tray, setTray] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const [applying, setApplying] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [step, setStep] = useState<{ stage?: string; done?: number; total?: number }>({});

  useEffect(() => {
    let cancelled = false; // a later run (the mode was switched) must not be overwritten by this one
    setProposal(null);
    setRows([]);
    setTray([]);
    setError("");
    setSeconds(0);
    setStep({});
    const timer = window.setInterval(() => {
      setSeconds((s) => s + 1);
      api.sortProgress(doc.id).then((p) => !cancelled && setStep(p), () => {});
    }, 1000);
    api.sortPages(doc.id, split).then(
      (p) => {
        if (cancelled) return;
        setProposal(p);
        const next = rowsFrom(p);
        setRows(next.rows);
        setTray(next.tray);
      },
      (e) => !cancelled && setError(e instanceof Error ? e.message : String(e)),
    ).finally(() => window.clearInterval(timer));
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [doc.id, split]);

  const pageById = useMemo(() => new Map(doc.pages.map((p) => [p.id, p])), [doc.pages]);

  /** Move an item to `to` (a row key or TRAY) at `index` (end when omitted). */
  const moveItem = (id: string, to: number, index?: number) => {
    let item: Item | undefined = tray.find((i) => i.id === id);
    const strip = (items: Item[]) => items.filter((i) => i.id !== id);
    for (const r of rows) item ??= r.items.find((i) => i.id === id);
    if (!item) return;
    const put = (items: Item[]) => {
      const out = strip(items);
      out.splice(index ?? out.length, 0, item!);
      return out;
    };
    setRows(rows.map((r) => ({ ...r, items: r.key === to ? put(r.items) : strip(r.items) })));
    setTray(to === TRAY ? put(tray) : strip(tray));
  };

  const nudge = (row: Row, i: number, by: number) => {
    const j = i + by;
    if (j < 0 || j >= row.items.length) return;
    moveItem(row.items[i].id, row.key, j);
  };

  const kept = rows.filter((r) => r.items.length > 0);
  const changed = split || kept[0]?.items.some((it, i) => doc.pages[i]?.id !== it.id);

  const apply = async () => {
    setApplying(true);
    setError("");
    try {
      if (split) {
        const out = await api.applySort(doc.id, kept.map((r) => ({
          page_ids: r.items.map((i) => i.id), name: r.name.trim(), name_source: r.edited ? "manual" : "ai",
        })));
        onApplied({ kind: "split", docs: out.documents, copied: kept.flatMap((r) => r.items.map((i) => i.id)) });
      } else {
        const previous = doc.pages.map((p) => p.id);
        const order = [...kept.flatMap((r) => r.items), ...tray].map((i) => i.id);
        onApplied({ kind: "reorder", doc: await api.reorder(doc.id, order), previous });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setApplying(false);
    }
  };

  const title = split ? "Sort pages with AI" : "Fix page order with AI";
  const loading = !proposal && !error;

  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title}>
        <header className="sheet-head">
          <h2 className="with-icon">{split ? <Sparkles /> : <ListOrdered />} {title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close" title="Close"><X /></button>
        </header>

        <div className="sheet-body">
          {loading && (
            <ProgressCard title={step.stage ?? "Starting"} elapsed={seconds}
              detail={step.total ? `${step.done ?? 0} of ${step.total}` : `${doc.pages.length} pages`}
              percent={step.total ? Math.round(100 * (step.done ?? 0) / step.total) : undefined} />
          )}
          {error && <p className="error" role="alert"><TriangleAlert /> {error}</p>}
          {proposal?.message && <p className="sort-note"><TriangleAlert /> {proposal.message}</p>}

          {proposal && (
            <p className="muted sort-summary">
              {kept.length === 0 ? "No change proposed." : split
                ? `Found ${kept.length} document${kept.length === 1 ? "" : "s"} in ${doc.pages.length} pages. The original scan stays as it is.`
                : "Proposed page order. Nothing changes until you apply it."}
            </p>
          )}

          {rows.map((row, n) => row.items.length > 0 && (
            <section key={row.key} className="sort-row"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { const id = e.dataTransfer.getData("text/x-page"); if (id) moveItem(id, row.key); }}>
              <div className="sort-row-head">
                {split ? (
                  <input className="title-input name-field" value={row.name} placeholder={`Document ${n + 1}`}
                    aria-label={`Name of document ${n + 1}`}
                    onChange={(e) => setRows(rows.map((r) => r.key === row.key ? { ...r, name: e.target.value, edited: true } : r))} />
                ) : <strong>Reading order</strong>}
                <span className="muted sort-count">{row.items.length} page{row.items.length === 1 ? "" : "s"}</span>
                <span className={`chip conf ${row.confidence}`} title={row.reason}>{LABEL[row.confidence]}</span>
              </div>
              {row.reason && <p className="muted sort-reason">{row.reason}</p>}
              <div className="sort-strip">
                {row.items.map((it, i) => (
                  <Thumb key={it.id} doc={doc} item={it} index={i} pageById={pageById}
                    expected={[...row.items.map((x) => x.position)].sort((a, b) => a - b)[i]}
                    onEarlier={i > 0 ? () => nudge(row, i, -1) : undefined}
                    onLater={i < row.items.length - 1 ? () => nudge(row, i, 1) : undefined}
                    targets={rows.filter((r) => r.key !== row.key && r.items.length > 0).map((r) => ({ key: r.key, label: r.name || `Document ${rows.indexOf(r) + 1}` }))}
                    onMove={(to) => moveItem(it.id, to)}
                    onDropBefore={(id) => moveItem(id, row.key, i)} />
                ))}
              </div>
            </section>
          ))}

          {tray.length > 0 && (
            <section className="sort-row tray"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { const id = e.dataTransfer.getData("text/x-page"); if (id) moveItem(id, TRAY); }}>
              <div className="sort-row-head">
                <strong className="with-icon"><Inbox /> Needs review</strong>
                <span className="muted sort-count">{split ? "not copied anywhere unless you move them into a document" : "kept at the end"}</span>
              </div>
              <div className="sort-strip">
                {tray.map((it, i) => (
                  <Thumb key={it.id} doc={doc} item={it} index={i} pageById={pageById}
                    targets={rows.filter((r) => r.items.length > 0).map((r) => ({ key: r.key, label: r.name || `Document ${rows.indexOf(r) + 1}` }))}
                    onMove={(to) => moveItem(it.id, to)} />
                ))}
              </div>
            </section>
          )}
        </div>

        <footer className="sheet-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={applying || loading || kept.length === 0 || !changed} onClick={apply}>
            {applying ? <LoaderCircle className="spin" /> : <Check />}
            {split ? `Create ${kept.length} document${kept.length === 1 ? "" : "s"}` : "Apply order"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function Thumb({ doc, item, index, expected, pageById, targets, onEarlier, onLater, onMove, onDropBefore }: {
  doc: Doc; item: Item; index: number; expected?: number; pageById: Map<string, Doc["pages"][number]>;
  targets: { key: number; label: string }[];
  onEarlier?: () => void; onLater?: () => void; onMove: (to: number) => void; onDropBefore?: (id: string) => void;
}) {
  const page = pageById.get(item.id);
  if (!page) return null;
  const moved = expected !== undefined && item.position !== expected && !item.why;
  return (
    <figure className="sort-thumb" draggable
      onDragStart={(e) => e.dataTransfer.setData("text/x-page", item.id)}
      onDragOver={(e) => onDropBefore && e.preventDefault()}
      onDrop={(e) => {
        const id = e.dataTransfer.getData("text/x-page");
        if (onDropBefore && id && id !== item.id) { e.stopPropagation(); onDropBefore(id); }
      }}>
      <img src={previewUrl(doc.id, page, 240)} alt={`Page ${item.position}`} loading="lazy" draggable={false} />
      <figcaption>
        <span className="num">{item.why ? `#${item.position}` : index + 1}</span>
        {moved && <span className="muted"> was #{item.position}</span>}
      </figcaption>
      {item.why && <span className="muted sort-why">{item.why}</span>}
      <div className="sort-thumb-tools">
        <button className="icon-btn" disabled={!onEarlier} onClick={onEarlier} aria-label="Move earlier" title="Move earlier"><ArrowLeft /></button>
        <button className="icon-btn" disabled={!onLater} onClick={onLater} aria-label="Move later" title="Move later"><ArrowRight /></button>
        {targets.length > 0 && (
          <select aria-label="Move to document" value="" onChange={(e) => e.target.value && onMove(Number(e.target.value))}>
            <option value="">Move to…</option>
            {targets.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        )}
      </div>
    </figure>
  );
}
