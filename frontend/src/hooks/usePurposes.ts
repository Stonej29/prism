import { useEffect, useState } from "react";
import { api } from "../api";
import type { Purpose } from "../types";

// Shared, app-wide cache of the user-defined purpose set. One fetch backs every
// pill picker / filter, and a settings edit calls refreshPurposes() to push the new
// list to all subscribers reactively (no prop drilling, no router).
let cache: Purpose[] | null = null;
const subscribers = new Set<(p: Purpose[]) => void>();

export function refreshPurposes(): Promise<Purpose[]> {
  return api.purposes().then((r) => {
    cache = r.items;
    subscribers.forEach((fn) => fn(cache!));
    return cache;
  });
}

export function usePurposes(): { purposes: Purpose[]; names: string[]; reload: () => Promise<Purpose[]> } {
  const [purposes, setPurposes] = useState<Purpose[]>(cache ?? []);
  useEffect(() => {
    subscribers.add(setPurposes);
    if (cache) setPurposes(cache);
    else refreshPurposes().catch(() => {});
    return () => {
      subscribers.delete(setPurposes);
    };
  }, []);
  return { purposes, names: purposes.map((p) => p.name), reload: refreshPurposes };
}
