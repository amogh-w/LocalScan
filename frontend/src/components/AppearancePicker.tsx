import type { CSSProperties } from "react";
import { Palette, Type } from "lucide-react";
import { ACCENTS, FLAVORS, TEXT_SIZES, useTheme, type Accent, type Flavor, type FlavorChoice } from "../theme";

const css = (vars: Record<string, string>) => vars as CSSProperties;

/** A tiny app mock-up rendered in the given flavor (the class scopes --ctp-* to this element). */
function MiniHalf({ flavor, accent }: { flavor: Flavor; accent: Accent }) {
  return (
    <div className={`mini-half ${flavor}`} style={css({ "--mini-accent": `var(--ctp-${accent})` })}>
      <div className="mini-bar" />
      <div className="mini-body">
        <div className="mini-line" />
        <div className="mini-line short" />
        <div className="mini-btn" />
      </div>
    </div>
  );
}

const CHOICES: { id: FlavorChoice; label: string; halves: Flavor[] }[] = [
  { id: "auto", label: "Auto", halves: ["latte", "mocha"] },
  ...FLAVORS.map((f) => ({ id: f.id as FlavorChoice, label: f.label, halves: [f.id as Flavor] })),
];

export default function AppearancePicker() {
  const [theme, setTheme] = useTheme();

  return (
    <section className="card form appearance">
      <h2 className="with-icon">
        <Palette /> Appearance
      </h2>

      <h3 id="text-label" className="with-icon"><Type /> Text size</h3>
      <div className="seg text-sizes" role="radiogroup" aria-labelledby="text-label">
        {TEXT_SIZES.map((x) => (
          <button key={x.id} role="radio" aria-checked={theme.text === x.id} className={theme.text === x.id ? "on" : ""}
            onClick={() => setTheme({ text: x.id })}>
            {x.label}
          </button>
        ))}
      </div>

      <h3 id="flavor-label">Flavor</h3>
      <div className="flavors" role="radiogroup" aria-labelledby="flavor-label">
        {CHOICES.map((c) => (
          <button
            key={c.id}
            role="radio"
            aria-checked={theme.flavor === c.id}
            className={`flavor${theme.flavor === c.id ? " on" : ""}`}
            onClick={() => setTheme({ flavor: c.id })}
            title={c.id === "auto" ? "Follow the system: Latte when light, Mocha when dark" : c.label}
          >
            <div className="mini">
              {c.halves.map((f) => (
                <MiniHalf key={f} flavor={f} accent={theme.accent} />
              ))}
            </div>
            <span className="flavor-name">{c.label}</span>
          </button>
        ))}
      </div>

      <h3 id="accent-label">Accent</h3>
      <div className="swatches" role="radiogroup" aria-labelledby="accent-label">
        {ACCENTS.map((a) => (
          <button
            key={a}
            role="radio"
            aria-checked={theme.accent === a}
            aria-label={a}
            title={a}
            className={`swatch${theme.accent === a ? " on" : ""}`}
            style={css({ "--sw": `var(--ctp-${a})` })}
            onClick={() => setTheme({ accent: a })}
          />
        ))}
      </div>
      <p className="accent-name">
        <b>{theme.accent}</b> is used for buttons, the crop frame and progress. Text size and colors are saved on this device.
      </p>
    </section>
  );
}
