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

export const ACCENTS = [
  "rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach",
  "yellow", "green", "teal", "sky", "sapphire", "blue", "lavender",
] as const;
export type Accent = (typeof ACCENTS)[number];

/** Global text size: the share of the browser's font size that <html> uses. Everything is sized in rem. */
export const TEXT_SIZES = [
  { id: "small", label: "Small", percent: 87.5 },
  { id: "default", label: "Default", percent: 93.75 },
  { id: "large", label: "Large", percent: 100 },
  { id: "xlarge", label: "Extra large", percent: 112.5 },
] as const;
export type TextSize = (typeof TEXT_SIZES)[number]["id"];

export interface Theme {
  flavor: FlavorChoice;
  accent: Accent;
  text: TextSize;
}

// Keep in sync with the inline script in index.html, which applies the theme before first paint.
const KEY = "localscan.theme";
export const DEFAULT_THEME: Theme = { flavor: "auto", accent: "blue", text: "default" };
const darkQuery = matchMedia("(prefers-color-scheme: dark)");

export function loadTheme(): Theme {
  try {
    const t = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return {
      flavor: t?.flavor === "auto" || FLAVORS.some((f) => f.id === t?.flavor) ? t.flavor : DEFAULT_THEME.flavor,
      accent: ACCENTS.includes(t?.accent) ? t.accent : DEFAULT_THEME.accent,
      text: TEXT_SIZES.some((x) => x.id === t?.text) ? t.text : DEFAULT_THEME.text,
    };
  } catch {
    return DEFAULT_THEME;
  }
}

function saveTheme(t: Theme) {
  try {
    localStorage.setItem(KEY, JSON.stringify(t));
  } catch {
    /* private mode / storage blocked: the theme just won't persist */
  }
}

/** Auto follows the OS: Latte when light, Mocha when dark. */
export const resolveFlavor = (f: FlavorChoice): Flavor => (f === "auto" ? (darkQuery.matches ? "mocha" : "latte") : f);

export function applyTheme(t: Theme) {
  const html = document.documentElement;
  html.classList.remove(...FLAVORS.map((f) => f.id));
  html.classList.add(resolveFlavor(t.flavor));
  html.style.setProperty("--accent", `var(--ctp-${t.accent})`);
  html.style.fontSize = `${TEXT_SIZES.find((x) => x.id === t.text)?.percent ?? 93.75}%`;
  // Browser chrome (mobile address bar) matches the app bar.
  const mantle = getComputedStyle(html).getPropertyValue("--ctp-mantle").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mantle);
}

/** Call once at startup: applies the saved theme and keeps "Auto" in step with the OS on every screen. */
export function initTheme() {
  applyTheme(loadTheme());
  darkQuery.addEventListener("change", () => applyTheme(loadTheme()));
}

export function useTheme(): [Theme, (patch: Partial<Theme>) => void] {
  const [theme, setTheme] = useState(loadTheme);

  useEffect(() => applyTheme(theme), [theme]);

  const update = (patch: Partial<Theme>) =>
    setTheme((old) => {
      const next = { ...old, ...patch };
      saveTheme(next);
      return next;
    });
  return [theme, update];
}
