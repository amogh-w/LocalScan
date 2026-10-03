import { useCallback, useEffect, useRef, useState } from "react";
import type { Point } from "../api";

interface Props {
  src: string;
  aspect: number; // image width / height
  corners: Point[]; // TL, TR, BR, BL, normalised 0..1
  onCommit: (corners: Point[]) => void;
}

type Drag = { kind: "corner"; index: number } | { kind: "edge"; index: number; last: Point };

const LOUPE = 120; // px
const ZOOM = 2.5;
const clamp = (v: number) => Math.min(1, Math.max(0, v));

export default function CornerEditor({ src, aspect, corners, onCommit }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [pts, setPts] = useState<Point[]>(corners);
  // The drag lives in a ref: pointer events can arrive faster than React re-renders.
  const dragRef = useRef<Drag | null>(null);
  const [drag, setDragState] = useState<Drag | null>(null);
  const setDrag = (d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  };
  const [focus, setFocus] = useState<Point | null>(null);
  const ptsRef = useRef(pts);
  const setPoints = (next: Point[]) => {
    ptsRef.current = next;
    setPts(next);
  };

  useEffect(() => {
    if (!dragRef.current) setPoints(corners);
  }, [corners]);

  const toNorm = useCallback((e: React.PointerEvent): Point => {
    const r = boxRef.current!.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  }, []);

  const start = (d: Drag) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setDrag(d.kind === "edge" ? { ...d, last: toNorm(e) } : d);
    setFocus(d.kind === "corner" ? ptsRef.current[d.index] : toNorm(e));
  };

  const move = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const p = toNorm(e);
    const old = ptsRef.current;
    if (drag.kind === "corner") {
      setPoints(old.map((q, i) => (i === drag.index ? p : q)));
    } else {
      const dx = p[0] - drag.last[0];
      const dy = p[1] - drag.last[1];
      const a = drag.index;
      const b = (drag.index + 1) % 4;
      setPoints(old.map((q, i) => (i === a || i === b ? [clamp(q[0] + dx), clamp(q[1] + dy)] : q)));
      setDrag({ ...drag, last: p });
    }
    setFocus(p);
  };

  const end = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    move(e); // the final position may come only with pointerup
    setDrag(null);
    setFocus(null);
    onCommit(ptsRef.current);
  };

  const poly = pts.map(([x, y]) => `${x},${y}`).join(" ");
  const mids: Point[] = pts.map((p, i) => {
    const q = pts[(i + 1) % 4];
    return [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
  });

  // Loupe sits in the top corner opposite the finger so it is never covered.
  const box = boxRef.current?.getBoundingClientRect();
  const loupeLeft = focus && focus[0] < 0.5;

  return (
    <div className="corner-editor" onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <div className="ce-box" ref={boxRef} style={{ aspectRatio: String(aspect), ["--ar" as string]: aspect }}>
        <img src={src} alt="" draggable={false} />
        <svg viewBox="0 0 1 1" preserveAspectRatio="none">
          <defs>
            <mask id="ce-mask">
              <rect x="0" y="0" width="1" height="1" fill="white" />
              <polygon points={poly} fill="black" />
            </mask>
          </defs>
          <rect x="0" y="0" width="1" height="1" className="ce-shade" mask="url(#ce-mask)" />
          <polygon points={poly} className="ce-quad" />
        </svg>
        {mids.map((m, i) => (
          <div
            key={`m${i}`}
            className="ce-handle ce-edge"
            style={{ left: `${m[0] * 100}%`, top: `${m[1] * 100}%` }}
            onPointerDown={start({ kind: "edge", index: i, last: m })}
          />
        ))}
        {pts.map((p, i) => (
          <div
            key={`c${i}`}
            className={`ce-handle ce-corner${drag?.kind === "corner" && drag.index === i ? " active" : ""}`}
            style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%` }}
            onPointerDown={start({ kind: "corner", index: i })}
          />
        ))}
        {focus && box && (
          <div
            className="ce-loupe"
            style={{
              width: LOUPE,
              height: LOUPE,
              [loupeLeft ? "right" : "left"]: 8,
              top: 8,
              backgroundImage: `url(${src})`,
              backgroundSize: `${box.width * ZOOM}px ${box.height * ZOOM}px`,
              backgroundPosition: `${LOUPE / 2 - focus[0] * box.width * ZOOM}px ${
                LOUPE / 2 - focus[1] * box.height * ZOOM
              }px`,
            }}
          />
        )}
      </div>
    </div>
  );
}
