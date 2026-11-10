import { Sparkles } from "lucide-react";
import { api, type Doc } from "../api";
import { AiRenameButton, AiSuggestion, useAiRename } from "./AiRename";
import NameEditor from "./NameEditor";

interface Props {
  doc: Doc;
  onChange: (doc: Doc) => void;
  onError: (message: string) => void;
}

/** Document name in the header: edit it by hand, or click the sparkle to ask the AI (only when clicked). */
export default function DocTitle({ doc, onChange, onError }: Props) {
  const ai = useAiRename(doc, onChange, onError);

  const rename = async (name: string) => {
    try {
      onChange(await api.renameDoc(doc.id, name));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="doc-title">
      <div className="doc-title-row">
        {doc.name_source === "ai" && (
          <span className="ai-mark" title="Named by AI">
            <Sparkles />
          </span>
        )}
        <NameEditor value={doc.name} onSave={rename} label="Document name" />
        <AiRenameButton ai={ai} doc={doc} />
      </div>
      <AiSuggestion ai={ai} />
    </div>
  );
}
