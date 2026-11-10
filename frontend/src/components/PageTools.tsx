import { ArrowLeft, ArrowRight, Contrast, Image, Maximize, RotateCcw, RotateCw, ScanSearch, ScanText, Sparkles, Trash2, type LucideIcon } from "lucide-react";
import type { Filter } from "../api";
import { Seg } from "./kit";
import { AsyncButton } from "./common";

const FILTERS: { id: Filter; label: string; icon: LucideIcon }[] = [
  { id: "enhanced", label: "Auto", icon: Sparkles },
  { id: "original", label: "Original", icon: Image },
  { id: "grayscale", label: "Gray", icon: Contrast },
  { id: "bw", label: "B&W", icon: ScanText },
];

interface Props {
  filter: Filter;
  index: number;
  count: number;
  busy: boolean;
  onFilter: (filter: Filter) => void;
  onDetect: () => Promise<unknown>;
  onFull: () => void;
  onRotate: (quarterTurns: 1 | -1) => void;
  onMove: (to: number) => void;
  onDelete: () => Promise<unknown>;
}

/** What acts on the page you are looking at: its color, its crop and rotation, its place in the document, delete. */
export default function PageTools({ filter, index, count, busy, onFilter, onDetect, onFull, onRotate, onMove, onDelete }: Props) {
  const icon = (label: string, node: React.ReactNode, onClick: () => void, disabled = false) => (
    <button className="btn btn-icon btn-sm btn-gray" disabled={busy || disabled} onClick={onClick} aria-label={label} title={label}>
      {node}
    </button>
  );
  return (
    <div className="page-tools">
      <Seg label="Color" className="seg-fill" value={filter} onChange={onFilter}
        options={FILTERS.map((f) => ({ id: f.id, title: f.label, disabled: busy, label: <><f.icon /><span className="tl">{f.label}</span></> }))} />
      <div className="tool-icons" role="toolbar" aria-label="Page tools">
        <AsyncButton className="btn btn-icon btn-sm btn-gray" disabled={busy} icon={<ScanSearch />} ariaLabel="Detect the page edges again"
          title="Detect the page edges again" onClick={onDetect} />
        {icon("Use the whole photo", <Maximize />, onFull)}
        {icon("Rotate left", <RotateCcw />, () => onRotate(-1))}
        {icon("Rotate right", <RotateCw />, () => onRotate(1))}
        <span className="sep" aria-hidden="true" />
        {icon("Move page earlier", <ArrowLeft />, () => onMove(index - 1), index === 0)}
        {icon("Move page later", <ArrowRight />, () => onMove(index + 1), index === count - 1)}
        <AsyncButton className="btn btn-icon btn-sm btn-danger-tinted ml-auto" disabled={busy} icon={<Trash2 />} ariaLabel="Delete page"
          title="Delete page" onClick={onDelete} />
      </div>
    </div>
  );
}
