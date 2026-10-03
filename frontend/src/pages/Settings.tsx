import { useEffect, useState } from "react";
import { api, type Health, type Settings } from "../api";

const OCR_LABELS: Record<string, string> = {
  paddle_local: "Built in (GPU, this app)",
  paddle_http: "PaddleOCR server (HTTP)",
};

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const check = () => {
    setChecking(true);
    api.health().then(setHealth).catch((e) => setError(e.message)).finally(() => setChecking(false));
  };

  useEffect(() => {
    api.getSettings().then(setS).catch((e) => setError(e.message));
    check();
  }, []);

  const save = async (patch: Parameters<typeof api.putSettings>[0]) => {
    try {
      setError(null);
      setS(await api.putSettings(patch));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      check();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="screen">
      <header className="bar">
        <a className="icon-btn" href="#/" aria-label="Back">
          ←
        </a>
        <div className="bar-title">Settings</div>
        {saved && <span className="muted small">Saved</span>}
      </header>
      <main className="content">
        {error && <p className="error">{error}</p>}
        {s && (
          <>
            <section className="card form">
              <h2>Translation (Ollama)</h2>
              <label>
                Model
                <select value={s.ollama_model} onChange={(e) => save({ ollama_model: e.target.value })}>
                  <option value="">First installed model{s.ollama_models[0] ? ` (${s.ollama_models[0]})` : ""}</option>
                  {s.ollama_models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              {s.ollama_error && <p className="error small">Can't list models: {s.ollama_error}</p>}
              <label>
                Ollama URL
                <input defaultValue={s.ollama_url} onBlur={(e) => e.target.value !== s.ollama_url && save({ ollama_url: e.target.value })} />
              </label>
            </section>

            <section className="card form">
              <h2>OCR (PaddleOCR)</h2>
              <label>
                Engine
                <select value={s.ocr} onChange={(e) => save({ ocr_engine: e.target.value })}>
                  {s.ocr_engines.map((e) => (
                    <option key={e} value={e}>
                      {OCR_LABELS[e] ?? e}
                    </option>
                  ))}
                </select>
              </label>
              {s.ocr === "paddle_http" && (
                <>
                  <label>
                    Endpoint URL
                    <input defaultValue={s.paddle_url} onBlur={(e) => e.target.value !== s.paddle_url && save({ paddle_url: e.target.value })} />
                  </label>
                  <p className="muted small">
                    Request format is set in <code>config.toml</code> (<code>ocr.paddle_http.request</code>).
                  </p>
                </>
              )}
              {s.ocr === "paddle_local" && (
                <p className="muted small">Runs on this PC's GPU inside the app. The first page takes a few extra seconds while models load.</p>
              )}
            </section>
          </>
        )}

        <section className="card form">
          <h2>Status</h2>
          {health ? (
            <ul className="health">
              <li className={health.ocr.ok ? "ok" : "bad"}>
                <b>OCR</b> {health.ocr.detail}
              </li>
              <li className={health.translator.ok ? "ok" : "bad"}>
                <b>Translator</b> {health.translator.detail}
              </li>
            </ul>
          ) : (
            <p className="muted">Checking…</p>
          )}
          <button className="btn small" onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Check again"}
          </button>
        </section>
      </main>
    </div>
  );
}
