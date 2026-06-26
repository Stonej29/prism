import { useEffect, useState } from "react";

// True when the viewport is phone-sized. Drives the default view (feed on
// mobile, three-pane Atlas on desktop). Mirrors the resize-listener pattern
// used elsewhere; no CSS media queries (the app styles entirely inline).
export function useIsMobile(breakpoint = 768): boolean {
  const query = `(max-width: ${breakpoint - 1}px)`;
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setIsMobile(mql.matches);
    mql.addEventListener("change", onChange);
    onChange();
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return isMobile;
}
