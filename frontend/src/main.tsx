import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import DocPage from "./pages/DocPage";
import Library from "./pages/Library";
import SettingsPage from "./pages/Settings";
import "./catppuccin.css";
import "./styles.css";
import { initTheme } from "./theme";

initTheme();

function useHashRoute() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#\/?/, "").split("/");
}

function App() {
  const [view, id] = useHashRoute();
  if (view === "doc" && id) return <DocPage key={id} id={id} />;
  if (view === "settings") return <SettingsPage />;
  if (view === "folder" && id) return <Library view={{ kind: "folder", id }} />;
  if (view === "tag" && id) return <Library view={{ kind: "tag", id }} />;
  if (view === "trash") return <Library view={{ kind: "trash" }} />;
  if (view === "unfiled") return <Library view={{ kind: "unfiled" }} />;
  return <Library view={{ kind: "all" }} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
