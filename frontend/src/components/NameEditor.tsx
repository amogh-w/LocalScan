import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  onSave: (name: string) => void;
  onDone?: () => void;
  autoFocus?: boolean;
  className?: string;
  label?: string;
}

/** Text field for a name: Enter or leaving the field saves, Esc cancels. Follows outside renames (e.g. AI). */
export default function NameEditor({ value, onSave, onDone, autoFocus, className = "title-input", label = "Name" }: Props) {
  const [draft, setDraft] = useState(value);
  const editing = useRef(false);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing.current) setDraft(value);
  }, [value]);

  useEffect(() => {
    if (autoFocus) ref.current?.select();
  }, [autoFocus]);

  const commit = () => {
    editing.current = false;
    const name = draft.trim();
    if (name && name !== value) onSave(name);
    else setDraft(value);
    onDone?.();
  };

  return (
    <input
      ref={ref}
      className={className}
      aria-label={label}
      value={draft}
      maxLength={120}
      autoFocus={autoFocus}
      onFocus={() => (editing.current = true)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          editing.current = false;
          setDraft(value);
          onDone?.();
          requestAnimationFrame(() => ref.current?.blur());
        }
      }}
    />
  );
}
