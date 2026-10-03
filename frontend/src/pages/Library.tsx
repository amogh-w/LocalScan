import QRCode from "qrcode";
import { ExternalLink, FileText, Pencil, Plus, Settings, Smartphone, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fileUrl, type Doc } from "../api";
import { AiRenameButton, AiSuggestion, useAiRename } from "../components/AiRename";
import NameEditor from "../components/NameEditor";
import { Downloads, StatusBadge } from "../components/common";

const isPhone = matchMedia("(pointer: coarse)").matches;

export default function Library() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qr, setQr] = useState<{ url: string; svg: string } | null>(null);


  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .listDocs()
        .then((d) => alive && (setDocs(d), setError(null)))
        .catch((e) => alive && setError(String(e.message ?? e)));
    load();
    const t = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (isPhone) return;
    api.serverInfo().then(async ({ lan_url }) => {
      // Same port as this page, so in dev the phone gets the Vite server with hot reload.
      const url = new URL(lan_url);
      url.port = location.port;
      const svg = await QRCode.toString(url.origin, { type: "svg", margin: 1 });
      setQr({ url: url.origin, svg });
    });
  }, []);

  const newScan = async () => {
    const doc = await api.createDoc();
    location.hash = `#/doc/${doc.id}`;
  };

  return (
    <div className="screen">
      <header className="bar">
        <h1>Local Scan</h1>
        <a className="icon-btn" href="#/settings" aria-label="Settings" title="Settings">
          <Settings />
        </a>
      </header>

      <main className="content">
        <button className="btn primary big" onClick={newScan}>
          <Plus /> New scan
        </button>

        {qr && (
          <details className="card qr-card">
            <summary className="with-icon">
              <Smartphone /> Scan from your phone
            </summary>
            <div className="qr" dangerouslySetInnerHTML={{ __html: qr.svg }} />
            <p className="muted">
              Same Wi-Fi, open <code>{qr.url}</code>
            </p>
          </details>
        )}

        {error && <p className="error">{error}</p>}
        {docs?.length === 0 && <p className="muted center">No documents yet.</p>}

        <ul className="doc-list">
          {docs?.map((d) => (
            <DocCard key={d.id} doc={d} onError={setError}
              onChange={(saved) => setDocs((all) => all && all.map((x) => (x.id === saved.id ? saved : x)))} />
          ))}
        </ul>
      </main>
    </div>
  );
}

function DocCard({ doc: d, onChange, onError }: { doc: Doc; onChange: (doc: Doc) => void; onError: (m: string) => void }) {
  const [renaming, setRenaming] = useState(false);
  const ai = useAiRename(d, onChange, onError);

  const rename = async (name: string) => {
    try {
      onChange(await api.renameDoc(d.id, name));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <li className="card doc-card">
      <div className="doc-main">
        <a href={`#/doc/${d.id}`} tabIndex={-1} aria-hidden>
          {d.pages[0] ? (
            <img className="doc-thumb" src={`/api/docs/${d.id}/pages/${d.pages[0].id}/image?max=200`} alt="" />
          ) : (
            <div className="doc-thumb empty">
              <FileText />
            </div>
          )}
        </a>
        <div className="doc-meta">
          {renaming ? (
            <NameEditor value={d.name} autoFocus className="title-input doc-rename" label="Document name"
              onSave={rename} onDone={() => setRenaming(false)} />
          ) : (
            <a className="doc-name" href={`#/doc/${d.id}`}>
              {d.name_source === "ai" && (
                <span className="ai-mark" title="Named by AI">
                  <Sparkles />
                </span>
              )}
              {d.name}
            </a>
          )}
          <div className="muted small">
            {d.pages.length} page{d.pages.length === 1 ? "" : "s"} ·{" "}
            {new Date(d.created * 1000).toLocaleDateString()}
          </div>
          <StatusBadge doc={d} />
        </div>
        {!renaming && (
          <div className="doc-card-actions">
            <AiRenameButton ai={ai} doc={d} />
            <button className="icon-btn" onClick={() => setRenaming(true)} aria-label={`Rename ${d.name}`} title="Rename">
              <Pencil />
            </button>
          </div>
        )}
      </div>
      <AiSuggestion ai={ai} />
      {d.status === "done" && d.outputs.translated && (
        <div className="doc-actions">
          <a className="btn small" href={fileUrl(d.id, "translated", true)} target="_blank">
            <ExternalLink /> Open English
          </a>
        </div>
      )}
      {d.status === "done" && <Downloads doc={d} compact />}
    </li>
  );
}
