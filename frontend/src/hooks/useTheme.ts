import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "prism-theme";
// Keep the browser/native status bar in step with the canvas background.
const THEME_COLOR: Record<Theme, string> = { dark: "#0a0c10", light: "#ffffff" };

function current(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" ? "light" : "dark";
}

/**
 * Light/dark theme for the whole app. The initial value is resolved before
 * paint by the inline script in index.html (saved preference → system); this
 * hook just reflects and toggles it, persisting the choice and updating the
 * theme-color meta. CSS variables (see index.html) do the actual restyling.
 */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(current);

  const apply = useCallback((next: Theme) => {
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore private-mode storage failures */
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", THEME_COLOR[next]);
    setTheme(next);
  }, []);

  useEffect(() => {
    apply(current());
  }, [apply]);

  const toggle = useCallback(() => apply(current() === "dark" ? "light" : "dark"), [apply]);
  return { theme, toggle };
}
