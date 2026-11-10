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
  const tool = (label: string, text: string, node: React.ReactNode, onClick: () => void, disabled = false) => (
    <button className="btn btn-sm btn-gray" disabled={busy || disabled} onClick={onClick} aria-label={label} title={label}>
      {node} {text}
    </button>
  );
  return (
    <div className="page-tools">
      <Seg label="Color" className="seg-fill" value={filter} onChange={onFilter}
        options={FILTERS.map((f) => ({ id: f.id, title: f.label, disabled: busy, label: <><f.icon /><span className="tl">{f.label}</span></> }))} />
      <div className="tool-icons" role="toolbar" aria-label="Page tools">
        <AsyncButton className="btn btn-sm btn-gray" disabled={busy} icon={<ScanSearch />} title="Detect the page edges again"
          onClick={onDetect}>
          Detect
        </AsyncButton>
        {tool("Use the whole photo", "Full", <Maximize />, onFull)}
        {tool("Rotate left", "Left", <RotateCcw />, () => onRotate(-1))}
        {tool("Rotate right", "Right", <RotateCw />, () => onRotate(1))}
        {tool("Move page earlier", "Earlier", <ArrowLeft />, () => onMove(index - 1), index === 0)}
        {tool("Move page later", "Later", <ArrowRight />, () => onMove(index + 1), index === count - 1)}
        <AsyncButton className="btn btn-sm btn-danger-tinted ml-auto" disabled={busy} icon={<Trash2 />} title="Delete page"
          onClick={onDelete}>
          Delete
        </AsyncButton>
      </div>
    </div>
  );
}
