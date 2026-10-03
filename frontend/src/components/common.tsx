import { fileUrl, type Doc, type OutputKind } from "../api";
import { CircleAlert, CircleCheck, CircleDashed, Clock, Download, LoaderCircle } from "lucide-react";

const LABELS: Record<OutputKind, string> = {
  translated: "English PDF",
  scan: "German scan",
  side_by_side: "Side by side",
};

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

export function Downloads({ doc, compact = false }: { doc: Doc; compact?: boolean }) {
  const kinds: OutputKind[] = ["translated", "scan", "side_by_side"];
  return (
    <div className={`downloads${compact ? " compact" : ""}`}>
      {kinds
        .filter((k) => doc.outputs[k])
        .map((k) => (
          <a key={k} className={`btn${k === "translated" && !compact ? " primary" : ""}`} href={fileUrl(doc.id, k)}>
            <Download /> {LABELS[k]}
          </a>
        ))}
    </div>
  );
}
