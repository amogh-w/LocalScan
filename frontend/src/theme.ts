import { useEffect, useState } from "react";

/** Catppuccin flavors; Latte is the only light one. */
export const FLAVORS = [
  { id: "latte", label: "Latte", dark: false },
  { id: "frappe", label: "Frappé", dark: true },
  { id: "macchiato", label: "Macchiato", dark: true },
  { id: "mocha", label: "Mocha", dark: true },
] as const;
export type Flavor = (typeof FLAVORS)[number]["id"];
export type FlavorChoice = Flavor | "auto";

/** The kit's accents (ui/theme.js). */
export const ACCENTS = [
  "rosewater", "flamingo", "pink", "mauve", "red", "peach", "yellow", "green", "teal", "sky", "blue", "lavender",
] as const;
export type Accent = (typeof ACCENTS)[number];

/** Corner radius, scaling every control, card and sheet (the kit's `--r-scale`). */
export const RADII = [
  { id: "tight", label: "Tight" },
  { id: "apple", label: "Apple" },
  { id: "soft", label: "Soft" },
] as const;
export type Radius = (typeof RADII)[number]["id"];

/** Text size: a multiplier on the kit's type scale (`--ts`, see app.css). */
export const TEXT_SIZES = [
  { id: "small", label: "Small", scale: 0.93 },
  { id: "default", label: "Default", scale: 1 },
  { id: "large", label: "Large", scale: 1.07 },
  { id: "xlarge", label: "Extra large", scale: 1.2 },
] as const;
export type TextSize = (typeof TEXT_SIZES)[number]["id"];

export interface Theme {
  flavor: FlavorChoice;
  accent: Accent;
  radius: Radius;
  text: TextSize;
}

declare global {
  // Defined by the kit's theme.js, a classic script that runs before the app.
  function applyTheme(): void;
}

// The kit owns these keys (ui/theme.js); the text size is ours. Keep index.html in step with TEXT_KEY.
const FLAVOR_KEY = "ui-flavor";
const ACCENT_KEY = "ui-accent";
const RADIUS_KEY = "ui-radius";
const TEXT_KEY = "localscan_text";
const OLD_KEY = "localscan.theme"; // before the kit: one JSON object

export const DEFAULT_THEME: Theme = { flavor: "auto", accent: "lavender", radius: "apple", text: "default" };

const get = (k: string) => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};
const set = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* private mode / storage blocked: the theme just won't persist */
  }
};

const scaleOf = (t: TextSize) => TEXT_SIZES.find((x) => x.id === t)?.scale ?? 1;

/** Carry the pre-kit choice over once: flavor and accent move to the kit's keys, then the old key goes. */
function migrate() {
  const raw = get(OLD_KEY);
  if (!raw) return;
  try {
    const old = JSON.parse(raw);
    if (!get(FLAVOR_KEY) && (old.flavor === "auto" || FLAVORS.some((f) => f.id === old.flavor))) set(FLAVOR_KEY, old.flavor);
    if (!get(ACCENT_KEY) && ACCENTS.includes(old.accent)) set(ACCENT_KEY, old.accent);
    const size = TEXT_SIZES.find((x) => x.id === old.text);
    if (!get(TEXT_KEY) && size) set(TEXT_KEY, String(size.scale));
  } catch {
    /* unreadable: ignore it */
  }
  try {
    localStorage.removeItem(OLD_KEY);
  } catch {
    /* ignore */
  }
}

export function loadTheme(): Theme {
  const flavor = get(FLAVOR_KEY);
  const accent = get(ACCENT_KEY);
  const radius = get(RADIUS_KEY);
  const scale = parseFloat(get(TEXT_KEY) ?? "");
  return {
    flavor: flavor === "auto" || FLAVORS.some((f) => f.id === flavor) ? (flavor as FlavorChoice) : DEFAULT_THEME.flavor,
    accent: ACCENTS.includes(accent as Accent) ? (accent as Accent) : DEFAULT_THEME.accent,
    radius: RADII.some((r) => r.id === radius) ? (radius as Radius) : DEFAULT_THEME.radius,
    text: TEXT_SIZES.find((x) => x.scale === scale)?.id ?? DEFAULT_THEME.text,
  };
}

function saveTheme(t: Theme) {
  set(FLAVOR_KEY, t.flavor);
  set(ACCENT_KEY, t.accent);
  set(RADIUS_KEY, t.radius);
  set(TEXT_KEY, String(scaleOf(t.text)));
}

/** The kit's applyTheme() reads its three keys; the text size and the browser chrome colour are ours. */
export function applyTheme(t: Theme) {
  saveTheme(t);
  window.applyTheme();
  const html = document.documentElement;
  html.style.setProperty("--ts", String(scaleOf(t.text)));
  // Browser chrome (mobile address bar) matches the app bar.
  const mantle = getComputedStyle(html).getPropertyValue("--ctp-mantle").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mantle);
}

/** Call once at startup: moves an old saved choice over, and keeps the browser chrome in step when Auto follows the OS. */
export function initTheme() {
  migrate();
  applyTheme(loadTheme());
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(loadTheme()));
}

export function useTheme(): [Theme, (patch: Partial<Theme>) => void] {
  const [theme, setTheme] = useState(loadTheme);

  useEffect(() => applyTheme(theme), [theme]);

  const update = (patch: Partial<Theme>) => setTheme((old) => ({ ...old, ...patch }));
  return [theme, update];
}
