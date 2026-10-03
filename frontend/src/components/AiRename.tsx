import { useState } from "react";
import { Check, LoaderCircle, Sparkles, X } from "lucide-react";
import { api, type Doc, type NameSuggestion } from "../api";

/** On-demand AI naming: ask for a suggestion, then the user applies or dismisses it. */
export function useAiRename(doc: Doc, onChange: (doc: Doc) => void, onError: (message: string) => void) {
  const [thinking, setThinking] = useState(false);
  const [suggestion, setSuggestion] = useState<NameSuggestion | null>(null);

  const suggest = async () => {
    setThinking(true);
    setSuggestion(null);
    try {
      setSuggestion(await api.suggestName(doc.id));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setThinking(false);
    }
  };

  const accept = async () => {
    if (!suggestion) return;
    try {
      onChange(await api.renameDoc(doc.id, suggestion.name, "ai"));
      setSuggestion(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return { thinking, suggestion, suggest, accept, dismiss: () => setSuggestion(null) };
}

type AiRename = ReturnType<typeof useAiRename>;

export function AiRenameButton({ ai, doc }: { ai: AiRename; doc: Doc }) {
  const ready = doc.pages.length > 0;
  return (
    <button className="icon-btn ai-btn" onClick={ai.suggest} disabled={ai.thinking || !ready}
      aria-label="Suggest a name with AI" title={ready ? "Suggest a name with AI" : "Add a page first"}>
      {ai.thinking ? <LoaderCircle className="spin" /> : <Sparkles />}
    </button>
  );
}

export function AiSuggestion({ ai }: { ai: AiRename }) {
  if (ai.thinking) return <p className="suggestion muted">Reading the letter…</p>;
  if (!ai.suggestion) return null;
  return (
    <div className="suggestion" role="status">
      <Sparkles className="sparkle" />
      <span className="suggestion-name">{ai.suggestion.name}</span>
      <button className="btn small primary" onClick={ai.accept}>
        <Check /> Use
      </button>
      <button className="icon-btn" onClick={ai.dismiss} aria-label="Dismiss" title="Dismiss">
        <X />
      </button>
    </div>
  );
}
