import {
  CircleAlert, CircleCheck, CircleDashed, Clock, Columns2, ExternalLink, FileText, Languages, LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import { fileUrl, type Doc, type OutputKind } from "../api";

const STATUS_ICONS = {
  draft: CircleDashed,
  queued: Clock,
  processing: LoaderCircle,
  done: CircleCheck,
  error: CircleAlert,
} as const;

export function StatusBadge({ doc }: { doc: Doc }) {
  const p = doc.progress;
  const text =
    doc.status === "processing" && p
      ? `${p.step}${p.total > 1 ? ` (${p.done + 1}/${p.total})` : ""}`
      : { draft: "Not processed", queued: "Waiting…", processing: "Working…", done: "Ready", error: "Failed" }[
          doc.status
        ];
  const Icon = STATUS_ICONS[doc.status];
  return (
    <span className={`badge ${doc.status}`}>
      <Icon className={doc.status === "processing" ? "spin" : undefined} />
      {text}
    </span>
  );
}

/** The three PDFs of a document, in the order shown everywhere. `kind` is the key the backend stores. */
const PDFS: { kind: OutputKind; short: string; full: string; icon: LucideIcon }[] = [
  { kind: "scan", short: "Original", full: "Original PDF", icon: FileText },
  { kind: "translated", short: "Translated", full: "Translated PDF", icon: Languages },
  { kind: "side_by_side", short: "Side by side", full: "Side by side", icon: Columns2 },
];

/**
 * Opens a finished document's PDFs in a new tab (the browser's viewer can save or print them).
 * "row" is three compact buttons for cards; "stack" is full-width rows for the options panel.
 */
export function PdfLinks({ doc, layout = "row" }: { doc: Doc; layout?: "row" | "stack" }) {
  return (
    <div className={`pdf-links ${layout}`}>
      {PDFS.filter((p) => doc.outputs[p.kind]).map((p) => (
        <a key={p.kind} className={`pdf-link${p.kind === "translated" ? " main" : ""}`} href={fileUrl(doc.id, p.kind, true)}
          target="_blank" rel="noopener" title={`${p.full}: opens in a new tab`} aria-label={`${p.full} (opens in a new tab)`}>
          <p.icon />
          <span>{layout === "stack" ? p.full : p.short}</span>
          {layout === "stack" && <ExternalLink className="ext" />}
        </a>
      ))}
    </div>
  );
}
