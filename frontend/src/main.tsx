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
  return <Library />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
