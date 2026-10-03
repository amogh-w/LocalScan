import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { api, fileUrl, type Doc } from "../api";
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
        <a className="icon-btn" href="#/settings" aria-label="Settings">
          ⚙
        </a>
      </header>

      <main className="content">
        <button className="btn primary big" onClick={newScan}>
          + New scan
        </button>

        {qr && (
          <details className="card qr-card">
            <summary>Scan from your phone</summary>
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
            <li key={d.id} className="card doc-card">
              <a className="doc-main" href={`#/doc/${d.id}`}>
                {d.pages[0] ? (
                  <img className="doc-thumb" src={`/api/docs/${d.id}/pages/${d.pages[0].id}/image?max=200`} alt="" />
                ) : (
                  <div className="doc-thumb empty" />
                )}
                <div>
                  <div className="doc-name">{d.name}</div>
                  <div className="muted small">
                    {d.pages.length} page{d.pages.length === 1 ? "" : "s"} ·{" "}
                    {new Date(d.created * 1000).toLocaleDateString()}
                  </div>
                  <StatusBadge doc={d} />
                </div>
              </a>
              {d.status === "done" && d.outputs.translated && (
                <div className="doc-actions">
                  <a className="btn small" href={fileUrl(d.id, "translated", true)} target="_blank">
                    Open English
                  </a>
                </div>
              )}
              {d.status === "done" && <Downloads doc={d} compact />}
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
