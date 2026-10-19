import { X } from "lucide-react";
import type { Tag } from "../api";
import { tone } from "./kit";

/** A tag in its Catppuccin accent color (the kit's tinted badge); optionally removable. */
export default function TagChip({ tag, onRemove }: { tag: Tag; onRemove?: () => void }) {
  return (
    <span className="badge badge-tint" style={tone(tag.color)}>
      {tag.name}
      {onRemove && (
        <button type="button" className="-mr-1 grid size-4 place-items-center rounded-full hover:bg-accent/25" onClick={onRemove}
          aria-label={`Remove tag ${tag.name}`} title="Remove tag">
          <X className="size-3" />
        </button>
      )}
    </span>
  );
}
