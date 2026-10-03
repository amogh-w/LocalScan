import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onSelect?: () => void;
  /** Items shown indented under this one when it is opened (used for the folder tree). */
  children?: (MenuItem & { depth?: number })[];
  disabled?: boolean;
  danger?: boolean;
  depth?: number;
}

/**
 * A context menu at the pointer. It stays inside the window, closes on Escape, an outside click, scrolling or
 * resizing, and is driven with the arrow keys. An item with `children` opens in place (an accordion), which
 * works on narrow screens and for touch where a side flyout would not fit.
 */
export default function ContextMenu({ x, y, items, onClose }: {
  x: number; y: number; items: MenuItem[]; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });
  const [open, setOpen] = useState<string | null>(null);

  // Keep the menu inside the window, also after a submenu opens and makes it taller.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const margin = 8;
    const { width, height } = el.getBoundingClientRect();
    setPos({
      left: Math.max(margin, Math.min(x, window.innerWidth - width - margin)),
      top: Math.max(margin, Math.min(y, window.innerHeight - height - margin)),
    });
  }, [x, y, open]);

  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const away = (e: Event) => !ref.current?.contains(e.target as Node) && onClose();
    const close = () => onClose();
    document.addEventListener("mousedown", away, true);
    document.addEventListener("touchstart", away, true);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("mousedown", away, true);
      document.removeEventListener("touchstart", away, true);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
    };
  }, [onClose]);

  const key = (e: React.KeyboardEvent) => {
    const buttons = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") buttons[(at + 1) % buttons.length]?.focus();
    else if (e.key === "ArrowUp") buttons[(at - 1 + buttons.length) % buttons.length]?.focus();
    else if (e.key === "Home") buttons[0]?.focus();
    else if (e.key === "End") buttons[buttons.length - 1]?.focus();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const choose = (item: MenuItem) => {
    if (item.children) {
      setOpen(open === item.label ? null : item.label);
    } else {
      onClose();
      item.onSelect?.();
    }
  };

  const row = (item: MenuItem, depth = 0) => (
    <button key={`${depth}:${item.label}`} role="menuitem" className={`ctx-item${item.danger ? " danger" : ""}`}
      disabled={item.disabled} style={depth ? { paddingLeft: `calc(var(--ctl-px-sm) + ${depth * 0.9}rem)` } : undefined}
      aria-haspopup={item.children ? "menu" : undefined} aria-expanded={item.children ? open === item.label : undefined}
      onClick={() => choose(item)}>
      {item.icon}
      <span className="ctx-label">{item.label}</span>
      {item.children && (open === item.label ? <ChevronDown /> : <ChevronRight />)}
    </button>
  );

  return (
    <div ref={ref} className="ctx-menu" role="menu" style={pos} onKeyDown={key} onContextMenu={(e) => e.preventDefault()}>
      {items.map((item) => (
        <div key={item.label}>
          {row(item)}
          {item.children && open === item.label && (
            <div className="ctx-sub" role="group">
              {item.children.map((c) => row(c, 1 + (c.depth ?? 0)))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
