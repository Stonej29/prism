import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { P } from "./theme";
import type { AskResult, GraphPayload, Idea, NoteDetail, Stats, TagCount } from "./types";
import { TopBar } from "./components/TopBar";
import { TreePane } from "./components/TreePane";
import { GraphPane } from "./components/GraphPane";
import { NotePane } from "./components/NotePane";
import { AskOverlay } from "./components/AskOverlay";
import { IdeaView } from "./components/IdeaView";
import type { Dispatch } from "./components/Omnibar";

interface AskState {
  open: boolean;
  question: string;
  result: AskResult | null;
  loading: boolean;
}
interface IdeaState {
  open: boolean;
  topic: string;
  idea: Idea | null;
  loading: boolean;
}

export default function App() {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [paneBusy, setPaneBusy] = useState(false);

  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Set<string> | null>(null);

  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<AskState>({ open: false, question: "", result: null, loading: false });
  const [idea, setIdea] = useState<IdeaState>({ open: false, topic: "", idea: null, loading: false });
  const [toast, setToast] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    const [g, t, s] = await Promise.all([api.graph(), api.tags(), api.stats()]);
    setGraph(g);
    setTags(t.items);
    setStats(s);
  }, []);

  useEffect(() => {
    refreshData().catch((e) => setToast(String(e)));
  }, [refreshData]);

  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(id);
    }
  }, [toast]);

  const selectNote = useCallback((id: string) => {
    setSelectedId(id);
    setNoteLoading(true);
    api
      .note(id)
      .then(setNote)
      .catch((e) => setToast(String(e)))
      .finally(() => setNoteLoading(false));
  }, []);

  const onSelectSource = (s: string | null) => {
    setSourceFilter(s);
    setActiveTag(null);
    setHighlight(null);
  };

  const onSelectTag = async (tag: string) => {
    setActiveTag(tag);
    setSourceFilter(null);
    try {
      const res = await api.notes({ tag, limit: 200 });
      setHighlight(new Set(res.items.map((n) => n.id)));
    } catch (e) {
      setToast(String(e));
    }
  };

  const dispatch = async (d: Dispatch) => {
    if (d.kind === "ask") {
      if (!d.text) return;
      setAsk({ open: true, question: d.text, result: null, loading: true });
      try {
        const result = await api.ask(d.text);
        setAsk((a) => ({ ...a, result, loading: false }));
      } catch (e) {
        setAsk((a) => ({ ...a, loading: false, result: { ok: false, answer: "", message: String(e), sources: [] } }));
      }
    } else if (d.kind === "find") {
      if (!d.text) return;
      setBusy(true);
      try {
        const res = await api.find(d.text);
        if (!res.configured) setToast("Semantic search is not configured.");
        setActiveTag(null);
        setSourceFilter(null);
        setHighlight(new Set(res.results.map((c) => c.id)));
      } catch (e) {
        setToast(String(e));
      } finally {
        setBusy(false);
      }
    } else if (d.kind === "idea") {
      setIdea({ open: true, topic: d.text, idea: null, loading: true });
      try {
        const res = await api.generateIdea(d.text || undefined);
        if (!res.ok) setToast(res.message);
        setIdea((s) => ({ ...s, idea: res.idea, loading: false }));
      } catch (e) {
        setToast(String(e));
        setIdea((s) => ({ ...s, loading: false }));
      }
    } else if (d.kind === "save") {
      setBusy(true);
      try {
        const res = await api.saveUrl(d.text);
        await refreshData();
        selectNote(res.note.id);
        setToast(res.created ? `Saved: ${res.note.title}` : `Already saved (${res.duplicate_reason})`);
      } catch (e) {
        setToast(String(e));
      } finally {
        setBusy(false);
      }
    }
  };

  const onReprocess = async (id: string) => {
    setPaneBusy(true);
    try {
      const res = await api.reprocess(id);
      setNote(res.note);
      setToast(res.message);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onDelete = async (id: string) => {
    setPaneBusy(true);
    try {
      await api.deleteNote(id);
      setSelectedId(null);
      setNote(null);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onEditTags = async (id: string, next: string[]) => {
    setPaneBusy(true);
    try {
      const updated = await api.editTags(id, next);
      setNote(updated);
      const t = await api.tags();
      setTags(t.items);
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onRate = async (id: string, rating: number) => {
    try {
      const updated = await api.rateIdea(id, rating);
      setIdea((s) => ({ ...s, idea: updated }));
    } catch (e) {
      setToast(String(e));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAsk((a) => ({ ...a, open: false }));
        setIdea((s) => ({ ...s, open: false }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", background: P.bg0, color: P.hi, fontFamily: P.sans, display: "flex", flexDirection: "column" }}>
      <TopBar busy={busy} onDispatch={dispatch} />
      <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
        <TreePane
          graph={graph}
          tags={tags}
          stats={stats}
          sourceFilter={sourceFilter}
          activeTag={activeTag}
          onSelectSource={onSelectSource}
          onSelectTag={onSelectTag}
        />
        <GraphPane
          graph={graph}
          sourceFilter={sourceFilter}
          onSourceFilter={onSelectSource}
          selectedId={selectedId}
          highlightIds={highlight}
          onSelect={selectNote}
        />
        <NotePane
          note={note}
          loading={noteLoading}
          busy={paneBusy}
          onSelectRelated={selectNote}
          onReprocess={onReprocess}
          onDelete={onDelete}
          onEditTags={onEditTags}
        />

        {ask.open && (
          <AskOverlay
            question={ask.question}
            result={ask.result}
            loading={ask.loading}
            onClose={() => setAsk((a) => ({ ...a, open: false }))}
            onSelectSource={(id) => {
              setAsk((a) => ({ ...a, open: false }));
              selectNote(id);
            }}
          />
        )}
        {idea.open && (
          <IdeaView
            topic={idea.topic}
            idea={idea.idea}
            loading={idea.loading}
            onClose={() => setIdea((s) => ({ ...s, open: false }))}
            onRate={onRate}
          />
        )}
      </div>

      {toast && (
        <div
          style={{
            position: "absolute",
            bottom: 20,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 40,
            background: P.bg2,
            border: `1px solid ${P.line}`,
            borderRadius: 8,
            padding: "9px 16px",
            fontFamily: P.sans,
            fontSize: 13,
            color: P.hi,
            boxShadow: "0 12px 30px rgba(0,0,0,0.4)",
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
