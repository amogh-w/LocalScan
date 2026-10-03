import type { CSSProperties } from "react";
import { X } from "lucide-react";
import type { Tag } from "../api";

/** A tag in its Catppuccin accent color; optionally removable. */
export default function TagChip({ tag, onRemove }: { tag: Tag; onRemove?: () => void }) {
  return (
    <span className="tag-chip" style={{ "--tag": `var(--ctp-${tag.color})` } as CSSProperties}>
      {tag.name}
      {onRemove && (
        <button onClick={onRemove} aria-label={`Remove tag ${tag.name}`} title="Remove tag">
          <X />
        </button>
      )}
    </span>
  );
}
