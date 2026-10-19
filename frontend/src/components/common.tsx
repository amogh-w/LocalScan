import {
  CircleAlert, CircleCheck, CircleDashed, Clock, Columns2, ExternalLink, FileText, Languages, LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { fileUrl, type Doc, type OutputKind } from "../api";
import { tone } from "./kit";

/** A button for an action that takes time: it shows a spinner in place of its icon and ignores clicks until done. */
export function AsyncButton({ onClick, icon, className = "btn btn-gray btn-sm", disabled, title, ariaLabel, children }: {
  onClick: () => unknown; icon?: ReactNode; className?: string; disabled?: boolean; title?: string; ariaLabel?: string;
  children?: ReactNode;
}) {
  const [pending, setPending] = useState(false);
  const click = async () => {
    setPending(true);
    try {
      await onClick();
    } finally {
      setPending(false);
    }
  };
  return (
    <button className={className} onClick={click} disabled={disabled || pending} aria-busy={pending} title={title}
      aria-label={ariaLabel}>
      {pending ? <LoaderCircle className="spin" /> : icon}
      {children}
    </button>
  );
}

/** A status as a badge: neutral while a draft, otherwise tinted by meaning. */
const STATUS_TONES = { draft: undefined, queued: "yellow", processing: undefined, done: "green", error: "red" } as const;

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
    <span className={`badge ${doc.status === "draft" ? "badge-outline" : "badge-tint"}`}
      style={STATUS_TONES[doc.status] ? tone(STATUS_TONES[doc.status]!) : undefined}>
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
        <a key={p.kind} className={`btn ${layout === "row" ? "btn-sm " : ""}${p.kind === "translated" ? "btn-tinted" : "btn-gray"}`} href={fileUrl(doc.id, p.kind, true)}
          target="_blank" rel="noopener" title={`${p.full}: opens in a new tab`} aria-label={`${p.full} (opens in a new tab)`}>
          <p.icon />
          <span>{layout === "stack" ? p.full : p.short}</span>
          {layout === "stack" && <ExternalLink className="ext" aria-hidden="true" />}
        </a>
      ))}
    </div>
  );
}
