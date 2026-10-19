import { ChevronDown } from "lucide-react";
import {
  useEffect, useLayoutEffect, useRef, type CSSProperties, type ReactNode, type SelectHTMLAttributes,
} from "react";

// ui/ui.js (loaded in index.html) puts UI on window. Its sprite is public/icons.svg, built from ui/icons.txt.
interface ConfirmOptions { title: string; text?: string; ok?: string; icon?: string; danger?: boolean }
declare global {
  interface Window {
    UI: { confirm(o: ConfirmOptions): Promise<boolean> };
  }
}

/** The kit's confirmation modal. Use it before anything disruptive or hard to undo. */
export const ask = (o: ConfirmOptions) => window.UI.confirm(o);

/** Colours an element's `--accent`, which the kit's badge-tint and chips read, with a Catppuccin color name. */
export const tone = (color: string) => ({ "--accent": `var(--ctp-${color})` }) as CSSProperties;

/**
 * The kit's segmented control. The kit's ui.js positions the sliding thumb for static markup; React markup
 * re-renders, so the thumb is measured here after every render and when the control resizes.
 */
export function Seg<T extends string>({ value, options, onChange, label, className = "", accent = false }: {
  value: T; options: { id: T; label: ReactNode; title?: string; disabled?: boolean }[]; onChange: (id: T) => void;
  label: string; className?: string; accent?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const place = () => {
    const seg = ref.current;
    const thumb = seg?.querySelector<HTMLElement>(".thumb");
    const on = seg?.querySelector<HTMLElement>("[aria-pressed=true]");
    if (!thumb || !on) return;
    thumb.style.width = `${on.offsetWidth}px`;
    thumb.style.transform = `translateX(${on.offsetLeft - 2}px)`;
  };
  useLayoutEffect(place);
  useEffect(() => {
    const seg = ref.current;
    if (!seg) return;
    const watch = new ResizeObserver(place);
    watch.observe(seg);
    return () => watch.disconnect();
  }, []);
  return (
    <div ref={ref} className={`seg${accent ? " seg-accent" : ""} ${className}`} role="group" aria-label={label}>
      <span className="thumb" />
      {options.map((o) => (
        <button key={o.id} type="button" aria-pressed={o.id === value} title={o.title} disabled={o.disabled}
          onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A kit field for a <select>: the kit's `field` plus its chevron. */
export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="select">
      <select className={`field ${className}`} {...rest}>{children}</select>
      <ChevronDown aria-hidden="true" />
    </div>
  );
}

/** A native modal <dialog> in the kit's style. It is open while mounted; Escape and a click outside close it. */
export function Dialog({ label, onClose, className = "", children }: {
  label: string; onClose: () => void; className?: string; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog ref={ref} className={`modal ${className}`} aria-label={label} onClose={onClose}
      onClick={(e) => e.target === ref.current && ref.current.close()}>
      {children}
    </dialog>
  );
}
