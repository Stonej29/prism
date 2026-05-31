import { useCallback, useState } from "react";

/**
 * A boolean toggle whose state is persisted in localStorage under `key`, so the
 * user's folded/expanded choices for sidebar sections survive reloads. Falls
 * back to `fallback` when nothing is stored (or storage is unavailable).
 */
export function usePersistentToggle(key: string, fallback: boolean): [boolean, () => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : raw === "1";
    } catch {
      return fallback;
    }
  });
  const toggle = useCallback(() => {
    setValue((v) => {
      const next = !v;
      try {
        localStorage.setItem(key, next ? "1" : "0");
      } catch {
        /* storage unavailable — keep in-memory state only */
      }
      return next;
    });
  }, [key]);
  return [value, toggle];
}
