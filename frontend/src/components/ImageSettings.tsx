import { useEffect, useState } from "react";
import { FileText, Image as ImageIcon, RotateCcw } from "lucide-react";
import type { Settings } from "../api";
import { AsyncButton } from "./common";

type Save = (patch: { images?: Record<string, number>; export?: Record<string, number | string> }) => Promise<void>;

const PRESET_INFO: Record<string, { title: string; hint: string }> = {
  archive: { title: "Archive", hint: "Best quality, biggest files" },
  standard: { title: "Standard", hint: "Sharp and reasonably small" },
  small: { title: "Small", hint: "For sharing and email" },
};

/** A slider that shows its value while dragging and saves once it is released (or a key is lifted). */
function Slider({ label, value, min, max, step, unit, onCommit }: {
  label: string; value: number; min: number; max: number; step: number; unit: string; onCommit: (v: number) => void;
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => v !== value && onCommit(v);
  return (
    <label className="range-row">
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => setV(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      <b>{v}{unit}</b>
    </label>
  );
}

/** Settings > Photos & PDFs: how big imported photos may be, how sharp the cleaned page is, and PDF quality. */
export default function ImageSettings({ s, save }: { s: Settings; save: Save }) {
  const limited = s.images.max_edge > 0;
  const preset = s.export.preset as string;
  const [dpi, quality] = s.export.effective;

  return (
    <section className="card form image-settings">
      <h2 className="with-icon"><ImageIcon /> Photos &amp; PDFs</h2>

      <h3 id="import-label">Photo import</h3>
      <div className="seg wide" role="radiogroup" aria-labelledby="import-label">
        <button role="radio" aria-checked={!limited} className={!limited ? "on" : ""}
          onClick={() => limited && save({ images: { max_edge: 0 } })}>Keep every pixel</button>
        <button role="radio" aria-checked={limited} className={limited ? "on" : ""}
          onClick={() => !limited && save({ images: { max_edge: s.defaults.images.max_edge || 4000 } })}>Limit size</button>
      </div>
      {limited ? (
        <Slider label="Longest side" value={s.images.max_edge} min={2000} max={8000} step={500} unit=" px"
          onCommit={(v) => save({ images: { max_edge: v } })} />
      ) : null}
      <p className="muted small">
        {limited
          ? "Bigger photos are shrunk before they are stored. Smaller uploads, a little less detail."
          : "Photos are stored exactly as the camera made them. Large photos take longer to upload and process."}
      </p>

      <h3 id="dpi-label">Page resolution</h3>
      <div className="seg wide" role="radiogroup" aria-labelledby="dpi-label">
        {s.page_dpis.map((d) => (
          <button key={d} role="radio" aria-checked={s.images.page_dpi === d} className={s.images.page_dpi === d ? "on" : ""}
            onClick={() => save({ images: { page_dpi: d } })}>
            {d}{d === s.defaults.images.page_dpi ? " (default)" : ""}
          </button>
        ))}
      </div>
      <p className="muted small">
        The cleaned page, in dpi (dots per inch). Higher is sharper for small print but slower and bigger. It can only
        be as sharp as your photo.
      </p>

      <h3 id="pdf-label" className="with-icon"><FileText /> PDF quality</h3>
      <div className="preset-grid" role="radiogroup" aria-labelledby="pdf-label">
        {Object.entries(s.presets).map(([id, p]) => (
          <button key={id} role="radio" aria-checked={preset === id} className={`preset${preset === id ? " on" : ""}`}
            onClick={() => save({ export: { preset: id } })}>
            <b>{PRESET_INFO[id]?.title ?? id}{id === s.defaults.export.preset && <span className="badge-default">Default</span>}</b>
            <span>{p.dpi} dpi, quality {p.quality}</span>
            <span className="muted small">{PRESET_INFO[id]?.hint}</span>
          </button>
        ))}
        <button role="radio" aria-checked={preset === "custom"} className={`preset${preset === "custom" ? " on" : ""}`}
          onClick={() => save({ export: { preset: "custom" } })}>
          <b>Custom</b>
          <span>Choose both yourself</span>
        </button>
      </div>
      {preset === "custom" && (
        <>
          <Slider label="Resolution" value={Number(s.export.dpi)} min={100} max={600} step={50} unit=" dpi"
            onCommit={(v) => save({ export: { dpi: v } })} />
          <Slider label="Quality" value={Number(s.export.quality)} min={40} max={100} step={5} unit=""
            onCommit={(v) => save({ export: { quality: v } })} />
        </>
      )}
      <p className="muted small">
        PDFs use {dpi} dpi at quality {quality}
        {dpi < Number(preset === "custom" ? s.export.dpi : s.presets[preset]?.dpi ?? dpi) ? " (limited by the page resolution above)" : ""}.
        The Original keeps its searchable text. Changes apply to new uploads and the next time a document is translated.
      </p>

      <AsyncButton className="btn small reset-btn" icon={<RotateCcw />}
        onClick={() => save({ images: s.defaults.images, export: s.defaults.export })}>
        Reset to defaults
      </AsyncButton>
    </section>
  );
}
