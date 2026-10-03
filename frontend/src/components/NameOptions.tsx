import { LoaderCircle, Sparkles, Tag } from "lucide-react";
import { api, type Doc } from "../api";
import { AiSuggestion, useAiRename } from "./AiRename";
import NameEditor from "./NameEditor";
import ProgressCard from "./ProgressCard";

interface Props {
  doc: Doc;
  onChange: (doc: Doc) => void;
  onError: (message: string) => void;
}

/** "Name" group in the Options panel: rename by hand, or ask the AI for a name (only when clicked). */
export default function NameOptions({ doc, onChange, onError }: Props) {
  const ai = useAiRename(doc, onChange, onError);

  const rename = async (name: string) => {
    try {
      onChange(await api.renameDoc(doc.id, name));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="opt-group wide">
      <h3 className="with-icon"><Tag /> Name</h3>
      <NameEditor value={doc.name} onSave={rename} className="title-input name-field" label="Document name" />
      <button className="btn small" onClick={ai.suggest} disabled={ai.thinking || doc.pages.length === 0}
        title={doc.pages.length ? "Read the letter and suggest a name" : "Add a page first"}>
        {ai.thinking ? <LoaderCircle className="spin" /> : <Sparkles />}
        {ai.thinking ? "Reading the letter…" : "Suggest name with AI"}
      </button>
      {ai.thinking ? (
        <ProgressCard title="Reading the letter" detail={`Looking at all ${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"} to find the date, sender and subject`} />
      ) : (
        <AiSuggestion ai={ai} />
      )}
    </section>
  );
}
