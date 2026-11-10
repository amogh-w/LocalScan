import { useState } from "react";
import { Ellipsis, Languages, RefreshCw, Trash2 } from "lucide-react";
import type { Doc, Page, PageTranslation } from "../api";
import ContextMenu from "./ContextMenu";
import ProgressCard from "./ProgressCard";
import { AsyncButton, PdfLinks, StatusBadge } from "./common";
import { tone } from "./kit";

interface Props {
  doc: Doc;
  page: Page | null; // the open page, for "This page"
  index: number;
  tstat: Record<string, PageTranslation>;
  busy: boolean;
  onGoTo: (index: number) => void;
  onTranslateAll: (again: boolean) => unknown;
  onTranslatePage: (page: Page, again: boolean) => unknown;
  onRemovePage: (page: Page) => unknown;
  onRemoveAll: () => unknown;
}

// A page is done when its text was read and every paragraph has a translation (a page with no text is done).
const pageDone = (s?: PageTranslation) => !!s && s.read && s.done === s.total;
const fullyTranslated = (s?: PageTranslation) => !!s && s.read && s.total > 0 && s.done === s.total;

/** Everything about translating this document: the one main action, progress per page, and the PDFs. */
export default function TranslatePanel({ doc, page, index, tstat, busy, onGoTo, onTranslateAll, onTranslatePage, onRemovePage, onRemoveAll }: Props) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const stat = page ? tstat[page.id] : undefined;
  const doneCount = doc.pages.filter((p) => pageDone(tstat[p.id])).length;
  const remaining = doc.pages.length - doneCount;
  const thisDone = fullyTranslated(stat);

  return (
    <section className="opt-group">
      <div className="opt-head">
        <h3 className="with-icon"><Languages /> Translate</h3>
        <StatusBadge doc={doc} />
        <button className="btn btn-icon btn-sm btn-plain ml-auto" aria-haspopup="menu" aria-label="More translation actions"
          title="Translate again, or remove translations"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setMenu({ x: r.right - 220, y: r.bottom + 4 });
          }}>
          <Ellipsis />
        </button>
      </div>
      {doc.status === "error" && <p className="error small">{doc.error}</p>}
      {busy && (doc.progress ? (
        <ProgressCard title={doc.progress.step} detail={doc.progress.detail} percent={doc.progress.percent}
          step={doc.progress.stage ? `Step ${doc.progress.stage} of ${doc.progress.stages}` : undefined}
          elapsed={doc.progress.elapsed} />
      ) : (
        <ProgressCard title={doc.status === "queued" ? "Waiting for its turn" : "Starting"}
          detail={doc.status === "queued" ? "Another document is being processed first" : undefined} />
      ))}

      {(remaining > 0 || doc.status !== "done") && (
        <AsyncButton className="btn btn-filled" disabled={busy} icon={<Languages />} onClick={() => onTranslateAll(false)}
          title="Translate the pages that are not done yet, then make the three PDFs">
          {remaining === 0 ? "Make the PDFs"
            : doneCount === 0 ? `Translate all ${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"}`
            : `Translate remaining (${remaining})`}
        </AsyncButton>
      )}

      <div className="translate-part">
        <div className="translate-line">
          <span className="muted small">{doneCount} of {doc.pages.length} translated</span>
          <div className="page-dots" role="group" aria-label="Translated pages">
            {doc.pages.map((p, i) => (
              <button key={p.id} type="button" onClick={() => onGoTo(i)}
                className={`page-dot${pageDone(tstat[p.id]) ? " on" : ""}${p.id === page?.id ? " cur" : ""}`}
                title={`Page ${i + 1}: ${pageDone(tstat[p.id]) ? "translated" : "not translated yet"}`}>
                {i + 1}
              </button>
            ))}
          </div>
        </div>
        {page && (
          <div className="translate-line">
            <span className="small">
              Page {index + 1}{" "}
              <span className={`badge ${thisDone ? "badge-tint" : "badge-outline"}`} style={thisDone ? tone("green") : undefined}>
                {thisDone ? "Translated" : stat && stat.done > 0 ? "Partly translated" : "Not translated"}
              </span>
            </span>
            <AsyncButton className={`btn btn-sm ${thisDone ? "btn-gray" : "btn-tinted"}`} disabled={busy}
              icon={thisDone ? <RefreshCw /> : <Languages />} onClick={() => onTranslatePage(page, thisDone)}
              title={thisDone ? "Translate this page again" : "Translate only this page"}>
              {thisDone ? "Translate again" : "Translate this page"}
            </AsyncButton>
          </div>
        )}
      </div>

      {doc.status === "done" && <PdfLinks doc={doc} />}

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} onClose={() => setMenu(null)} items={[
          { label: "Translate all pages again", icon: <RefreshCw />, disabled: busy, onSelect: () => onTranslateAll(true) },
          { label: "Remove translation of this page", icon: <Trash2 />, disabled: busy || !page || !stat?.done, onSelect: () => page && onRemovePage(page) },
          { label: "Remove all translations and PDFs", icon: <Trash2 />, danger: true, disabled: busy, onSelect: () => onRemoveAll() },
        ]} />
      )}
    </section>
  );
}
