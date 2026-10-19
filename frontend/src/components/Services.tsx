import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, CircleCheck, CircleX, Play, RefreshCw, ScrollText, Square } from "lucide-react";
import { api, type Health, type ServiceInfo } from "../api";
import { AsyncButton } from "./common";
import { ask, tone } from "./kit";

type Check = { ok: boolean; detail: string };

/** Which part of /api/health describes which service. */
const checkOf = (id: string, h: Health | null): Check | undefined =>
  id === "ollama" ? h?.translator : id === "paddle" ? h?.ocr : undefined;

const STATE: Record<ServiceInfo["state"], { label: string; color?: string }> = {
  running: { label: "Running", color: "green" },
  starting: { label: "Starting", color: "yellow" },
  stopped: { label: "Stopped" },
};

/** The last lines of a service's log, refreshed while it is open. */
function Logs({ id }: { id: string }) {
  const [text, setText] = useState<string | null>(null);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.serviceLogs(id).then((r) => live && setText(r.text), () => {});
    load();
    const t = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [id]);
  useEffect(() => {
    const el = box.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight; // follow the end
  }, [text]);
  return (
    <pre ref={box} className="log" tabIndex={0} aria-label="Log">
      {text === null ? "Loading…" : text || "No log output yet."}
    </pre>
  );
}

/**
 * Start, stop, check and read the logs of the helper services. Nothing starts by itself: a service runs only after
 * its Start button is clicked. State is polled every two seconds; the health check (which asks the service to do a
 * little work) runs on opening, after a start or stop, and on request.
 */
export default function Services({ onError }: { onError: (message: string | null) => void }) {
  const [list, setList] = useState<ServiceInfo[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(false);
  const [logs, setLogs] = useState<string | null>(null);
  const seen = useRef<Record<string, string>>({});

  const check = useCallback(() => {
    setChecking(true);
    api.health().then(setHealth).catch((e) => onError(e.message)).finally(() => setChecking(false));
  }, [onError]);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.services().then((next) => {
        if (!live) return;
        setList(next);
        // a service that just came up or went down: its health has changed too
        if (next.some((s) => seen.current[s.id] && seen.current[s.id] !== s.state && s.state !== "starting")) check();
        seen.current = Object.fromEntries(next.map((s) => [s.id, s.state]));
      }, () => {});
    load();
    const t = setInterval(load, 2000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [check]);

  useEffect(check, [check]);

  const act = async (fn: () => Promise<ServiceInfo>) => {
    try {
      onError(null);
      const done = await fn();
      setList((all) => all && all.map((s) => (s.id === done.id ? done : s)));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="card stack">
      <h2 className="with-icon"><Activity /> Services</h2>
      <p className="muted small">
        Nothing here starts by itself. Start what you need: translating needs Ollama, and reading pages needs PaddleOCR.
      </p>
      {list === null ? <p className="muted">Loading…</p> : list.map((s) => {
        const c = checkOf(s.id, health);
        const color = STATE[s.state].color;
        return (
          <div key={s.id} className="service">
            <div className="service-head">
              <strong>{s.name}</strong>
              <span className={`badge ${color ? "badge-tint" : "badge-outline"}`} style={color ? tone(color) : undefined}>
                {s.state === "starting" && <RefreshCw className="spin" />}{STATE[s.state].label}
              </span>
            </div>
            {s.detail && <p className="muted small">{s.detail}</p>}
            {c && s.state === "running" && (
              <p className={`small with-icon ${c.ok ? "ok" : "error"}`}>
                {c.ok ? <CircleCheck /> : <CircleX />} {c.detail}
              </p>
            )}
            <div className="service-actions">
              {s.state === "stopped" ? (
                <AsyncButton className="btn btn-sm btn-tinted" icon={<Play />} onClick={() => act(() => api.startService(s.id))}>
                  Start
                </AsyncButton>
              ) : (
                <AsyncButton className="btn btn-sm btn-danger-tinted" icon={<Square />}
                  onClick={async () => await ask({
                    title: `Stop ${s.name}?`, text: "Translating or reading pages will not work until it is started again.",
                    ok: "Stop", icon: "power", danger: true,
                  }) && act(() => api.stopService(s.id))}>
                  Stop
                </AsyncButton>
              )}
              <button className="btn btn-sm btn-gray" aria-pressed={logs === s.id} onClick={() => setLogs(logs === s.id ? null : s.id)}>
                <ScrollText /> Logs
              </button>
            </div>
            {logs === s.id && <Logs id={s.id} />}
          </div>
        );
      })}
      <button className="btn btn-gray btn-sm self-start" onClick={check} disabled={checking}>
        <RefreshCw className={checking ? "spin" : undefined} />
        {checking ? "Checking…" : "Check again"}
      </button>
    </section>
  );
}
