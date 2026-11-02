import { useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";
const KEY = "theme";

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** Browser UI (status bar, PWA title bar) follows the app's surface color, including manual overrides. */
function syncThemeColor() {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim();
  if (!color) return;
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", color));
}

function apply(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  syncThemeColor();
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    apply(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", syncThemeColor);
    return () => mq.removeEventListener("change", syncThemeColor);
  }, [theme]);
  const cycle = () => {
    const next: Theme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      /* storage unavailable */
    }
    setTheme(next);
  };
  return [theme, cycle];
}
