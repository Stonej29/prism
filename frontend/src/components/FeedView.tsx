import { useCallback, useEffect, useRef, useState } from "react";
import { Check, SlidersHorizontal } from "lucide-react";
import { api } from "../api";
import { P } from "../theme";
import type { NoteSummary } from "../types";
import { FeedCard } from "./FeedCard";
import { FeedDetail } from "./FeedDetail";
import { Spinner } from "./Spinner";

type Tab = "inbox" | "rediscovery" | "all";
const PAGE_SIZE = 20;
const TABS: { key: Tab; label: string }[] = [
  { key: "inbox", label: "Inbox" },
  { key: "rediscovery", label: "Rediscover" },
  { key: "all", label: "All" },
];
const SORTS: { key: string; label: string }[] = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "relevance", label: "Top score" },
];
// Single-purpose filters for the inbox (Keep is excluded from the queue by design;
// "Unsorted" => notes with no purpose set). null = all purposes.
const PURPOSE_FILTERS = ["Thesis", "Work", "Self-Host", "Dataset", "Unsorted"];

function PopLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: P.mono, fontSize: 10, color: P.faint, textTransform: "uppercase", letterSpacing: 1.2, padding: "6px 14px 4px" }}>
      {children}
    </div>
  );
}

function PopOption({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
        background: "none",
        border: "none",
        padding: "8px 14px",
        cursor: "pointer",
        color: active ? P.hi : P.mid,
        fontFamily: P.sans,
        fontSize: 13.5,
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
      {active && <Check size={14} color={P.accent} />}
    </button>
  );
}

/**
 * Mobile-first reading feed: a scrolling list of saved notes the user works
 * through and marks read. Defaults to the inbox review queue, with tabs for
 * rediscovery and the full corpus. Reuses the same REST API as the Atlas UI.
 */
export function FeedView({
  onClose,
  onReadChanged,
}: {
  onClose?: () => void;
  onReadChanged?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("inbox");
  const [sort, setSort] = useState("newest");
  const [purpose, setPurpose] = useState<string | null>(null);
  const [items, setItems] = useState<NoteSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [controlsOpen, setControlsOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  // Guards against overlapping page loads.
  const loadingRef = useRef(false);

  const fetchPage = useCallback(
    async (reset: boolean) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      setError(null);
      const nextOffset = reset ? 0 : offset;
      try {
        let page: NoteSummary[];
        let more = false;
        if (tab === "rediscovery") {
          // Rediscovery is a small fixed set — no pagination.
          page = (await api.feedRediscovery("forgotten_gems")).items;
        } else if (tab === "inbox") {
          page = (await api.inbox({ sort, purpose, limit: PAGE_SIZE, offset: nextOffset })).items;
          more = page.length === PAGE_SIZE;
        } else {
          page = (await api.notes({ limit: PAGE_SIZE, offset: nextOffset })).items;
          more = page.length === PAGE_SIZE;
        }
        setItems((prev) => (reset ? page : [...prev, ...page]));
        setOffset(nextOffset + page.length);
        setHasMore(more);
      } catch (e) {
        setError(String(e));
        setHasMore(false);
      } finally {
        loadingRef.current = false;
        setLoading(false);
      }
    },
    [tab, sort, purpose, offset],
  );

  // Reload from the top whenever the tab / sort / purpose filter changes.
  useEffect(() => {
    setItems([]);
    setOffset(0);
    setHasMore(true);
    scrollRef.current?.scrollTo({ top: 0 });
    fetchPage(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, sort, purpose]);

  // Keep loading until the list overflows the viewport or is exhausted — covers
  // short pages where a scroll event would never fire.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !hasMore || loading || loadingRef.current) return;
    if (el.scrollHeight <= el.clientHeight + 4) fetchPage(false);
  }, [items, hasMore, loading, fetchPage]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || loadingRef.current || !hasMore) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 320) fetchPage(false);
  };

  // Close the filter/sort popover on an outside click.
  useEffect(() => {
    if (!controlsOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!controlsRef.current?.contains(e.target as Node)) setControlsOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [controlsOpen]);

  const markRead = async (id: string) => {
    setBusyId(id);
    try {
      await api.setStatus(id, "reviewed");
      const stamp = new Date().toISOString();
      setItems((prev) =>
        tab === "inbox"
          ? prev.filter((n) => n.id !== id) // leaves the review queue
          : prev.map((n) => (n.id === id ? { ...n, date_reviewed: stamp } : n)),
      );
      onReadChanged?.();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const empty = !loading && items.length === 0 && !error;

  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 10, display: "flex", flexDirection: "column", background: P.bg0 }}>
      {/* Single header row: tabs + one quiet filter/sort control (inbox only) */}
      <div style={{ flexShrink: 0, position: "relative", display: "flex", alignItems: "stretch", gap: 4, padding: "0 12px", borderBottom: `1px solid ${P.line}`, background: P.bg0 }}>
        {onClose && (
          <button onClick={onClose} title="Back to Atlas" style={{ alignSelf: "center", marginRight: 2, background: "transparent", border: "none", color: P.lo, fontFamily: P.mono, fontSize: 18, cursor: "pointer", padding: "0 6px" }}>
            ×
          </button>
        )}
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => { setTab(t.key); setControlsOpen(false); }}
              style={{
                padding: "14px 12px 11px",
                background: "transparent",
                border: "none",
                borderBottom: `2px solid ${active ? P.accent : "transparent"}`,
                color: active ? P.hi : P.lo,
                fontFamily: P.sans,
                fontSize: 14.5,
                fontWeight: active ? 600 : 500,
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          );
        })}

        {tab === "inbox" && (
          <div style={{ marginLeft: "auto", alignSelf: "center" }}>
            <button
              onClick={() => setControlsOpen((o) => !o)}
              title="Filter & sort"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: "none",
                padding: "6px 4px",
                cursor: "pointer",
                color: purpose ? P.accent : P.lo,
                fontFamily: P.sans,
                fontSize: 13,
              }}
            >
              <SlidersHorizontal size={16} />
              {purpose && <span>{purpose}</span>}
            </button>
          </div>
        )}

        {controlsOpen && tab === "inbox" && (
          <div
            ref={controlsRef}
            style={{
              position: "absolute",
              top: "100%",
              right: 10,
              marginTop: 4,
              zIndex: 20,
              minWidth: 180,
              background: P.bg1,
              border: `1px solid ${P.line}`,
              borderRadius: 12,
              padding: "8px 0",
              boxShadow: "0 16px 40px rgba(0,0,0,0.4)",
            }}
          >
            <PopLabel>Show</PopLabel>
            {[{ key: null, label: "All purposes" }, ...PURPOSE_FILTERS.map((p) => ({ key: p as string | null, label: p }))].map((p) => (
              <PopOption key={p.label} label={p.label} active={purpose === p.key} onClick={() => setPurpose(p.key)} />
            ))}
            <div style={{ height: 1, background: P.line, margin: "6px 0" }} />
            <PopLabel>Sort</PopLabel>
            {SORTS.map((s) => (
              <PopOption key={s.key} label={s.label} active={sort === s.key} onClick={() => setSort(s.key)} />
            ))}
          </div>
        )}
      </div>

      {/* Scrollable feed */}
      <div ref={scrollRef} onScroll={onScroll} style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch", padding: "0 18px 40px" }}>
        <div style={{ display: "flex", flexDirection: "column", maxWidth: 640, margin: "0 auto" }}>
          {error && <div style={{ fontFamily: P.sans, fontSize: 14, color: P.arxiv, padding: 8 }}>{error}</div>}
          {empty && (
            <div style={{ fontFamily: P.sans, fontSize: 14, color: P.lo, textAlign: "center", padding: "48px 16px" }}>
              {tab === "rediscovery"
                ? "No forgotten gems right now."
                : tab === "all"
                  ? "No notes yet."
                  : purpose
                    ? `Nothing left to read in ${purpose}.`
                    : "Inbox zero — nothing left to read 🎉"}
            </div>
          )}
          {items.map((n) => (
            <FeedCard key={n.id} note={n} busy={busyId === n.id} onOpen={() => setDetailId(n.id)} onRead={() => markRead(n.id)} />
          ))}
          {loading && (
            <div style={{ display: "flex", justifyContent: "center", padding: 20 }}>
              <Spinner label={items.length ? "Loading more…" : "Loading…"} />
            </div>
          )}
        </div>
      </div>

      {detailId && (
        <FeedDetail
          noteId={detailId}
          onClose={() => setDetailId(null)}
          onRead={(id) => {
            markRead(id);
            setDetailId(null);
          }}
          onChanged={(n) => {
            // Reflect title/purpose edits in the list. If the inbox is filtered
            // to one purpose and the note no longer matches, drop it.
            const filteredOut =
              tab === "inbox" &&
              purpose != null &&
              (purpose === "Unsorted" ? n.purpose != null : n.purpose !== purpose);
            setItems((prev) =>
              filteredOut
                ? prev.filter((it) => it.id !== n.id)
                : prev.map((it) => (it.id === n.id ? { ...it, title: n.title, purpose: n.purpose } : it)),
            );
          }}
        />
      )}
    </div>
  );
}
