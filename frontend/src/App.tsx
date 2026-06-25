import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
import { P, srcLabel } from "./theme";
import type { ActivityEntry, AskResult, GraphPayload, Idea, MaintenanceStatus, NoteDetail, Proposal, Stats, TagCount, TreeNode, Usage } from "./types";
import { TopBar } from "./components/TopBar";
import { TreePane } from "./components/TreePane";
import { GraphPane } from "./components/GraphPane";
import { NotePane } from "./components/NotePane";
import { AskOverlay } from "./components/AskOverlay";
import { ProposalsOverlay } from "./components/ProposalsOverlay";
import { IdeaView } from "./components/IdeaView";
import { FileViewer, type OpenFile } from "./components/FileViewer";
import { ActivityLog } from "./components/ActivityLog";
import { SettingsOverlay } from "./components/SettingsOverlay";
import { Login } from "./components/Login";
import type { IdeaStatus } from "./components/Lightbulb";

interface AskState {
  open: boolean;
  question: string;
  result: AskResult | null;
  loading: boolean;
}
interface IdeaJob {
  status: IdeaStatus;
  idea: Idea | null;
  open: boolean;
  topic: string;
}
interface ProposalsState {
  open: boolean;
  items: Proposal[];
  pending: number;
  loading: boolean;
  busyId: string | null;
  runningJob: "ingest" | "traverse" | null;
}
interface ActivityState {
  open: boolean;
  loading: boolean;
  items: ActivityEntry[];
}

const LEFT_CLOSED_W = 32;
const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

export default function App() {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [paneBusy, setPaneBusy] = useState(false);
  // Multiple notes can be reprocessing/researching at once — keyed by note id.
  const [processingNotes, setProcessingNotes] = useState<Record<string, "reprocess" | "repersonalize" | "research">>({});

  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(false);
  const [leftWidth, setLeftWidth] = useState(264);
  const [rightWidth, setRightWidth] = useState(392);

  const [sourceFilters, setSourceFilters] = useState<string[]>([]);
  const [tagFilters, setTagFilters] = useState<string[]>([]);
  const [topicFilters, setTopicFilters] = useState<number[]>([]);
  const [flagFilters, setFlagFilters] = useState<string[]>([]);
  const [purposeFilters, setPurposeFilters] = useState<string[]>([]);
  const [highlight, setHighlight] = useState<Set<string> | null>(null);
  const [filterPreview, setFilterPreview] = useState<Set<string> | null>(null);
  const [minAgeDays, setMinAgeDays] = useState(0); // 0 = show all; higher = only newer
  const [minScore, setMinScore] = useState(0); // 0 = no score filter

  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ask, setAsk] = useState<AskState>({ open: false, question: "", result: null, loading: false });
  const [ideaJob, setIdeaJob] = useState<IdeaJob>({ status: "idle", idea: null, open: false, topic: "" });
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [proposals, setProposals] = useState<ProposalsState>({ open: false, items: [], pending: 0, loading: false, busyId: null, runningJob: null });
  const [maintenanceStatus, setMaintenanceStatus] = useState<MaintenanceStatus | null>(null);
  const [activity, setActivity] = useState<ActivityState>({ open: false, loading: false, items: [] });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const selectedIdRef = useRef<string | null>(null);

  // null = still checking; false = show login/setup; true = show vault.
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
    api
      .authStatus()
      .then((s) => {
        setNeedsSetup(s.needs_setup);
        setAuthed(s.authenticated);
      })
      .catch(() => setAuthed(false));
    return () => setUnauthorizedHandler(null);
  }, []);

  const selectedAction = selectedId ? processingNotes[selectedId] ?? null : null;
  const clearProcessing = (id: string, action: "reprocess" | "repersonalize" | "research") =>
    setProcessingNotes((m) => (m[id] === action ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== id)) : m));

  const noteKind = useMemo(() => {
    const m: Record<string, string> = {};
    for (const n of graph?.nodes ?? []) m[n.id] = n.source_kind;
    return m;
  }, [graph]);

  const refreshData = useCallback(async () => {
    const [g, t, s, tr, pr, u] = await Promise.all([
      api.graph(),
      api.tags(),
      api.stats(),
      api.tree(),
      api.proposals(),
      api.usage(),
    ]);
    setGraph(g);
    setTags(t.items);
    setStats(s);
    setTree(tr);
    setUsage(u);
    setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending }));
  }, []);

  useEffect(() => {
    if (authed !== true) return;
    refreshData().catch((e) => setToast(String(e)));
  }, [authed, refreshData]);

  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(id);
    }
  }, [toast]);

  useEffect(() => {
    if (proposals.runningJob !== "traverse") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await api.maintenanceStatus();
        if (!cancelled) setMaintenanceStatus(status);
      } catch {
        // The POST result still reports failure; avoid noisy poll toasts.
      }
    };
    poll();
    const id = setInterval(poll, 700);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [proposals.runningJob]);

  const selectNote = useCallback((id: string) => {
    setSelectedId(id);
    setRightOpen(true);
    setHighlight(null); // clear any related/tag highlight when focusing a node
    setNoteLoading(true);
    api
      .note(id)
      .then(setNote)
      .catch((e) => setToast(String(e)))
      .finally(() => setNoteLoading(false));
  }, []);

  const deselect = useCallback(() => {
    setSelectedId(null);
    setNote(null);
    setRightOpen(false);
    setHighlight(null);
  }, []);

  const onLogout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore — fall through to the login screen regardless */
    }
    setSettingsOpen(false);
    setAuthed(false);
  }, []);

  const clearFanoutFilters = () => {
    setSourceFilters([]);
    setTagFilters([]);
    setTopicFilters([]);
    setFlagFilters([]);
    setPurposeFilters([]);
    setHighlight(null);
    setFilterPreview(null);
  };

  const clearAllFilters = () => {
    clearFanoutFilters();
    setMinAgeDays(0);
    setMinScore(0);
  };

  const selectSource = (source: string, additive = false) => {
    setHighlight(null);
    if (!additive) {
      const selected = sourceFilters.length === 1 && sourceFilters[0] === source && tagFilters.length === 0 && topicFilters.length === 0 && flagFilters.length === 0 && purposeFilters.length === 0;
      setSourceFilters(selected ? [] : [source]);
      setTagFilters([]);
      setTopicFilters([]);
      setFlagFilters([]);
      setPurposeFilters([]);
      return;
    }
    setSourceFilters((prev) => (prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]));
  };

  const selectTag = (tag: string, additive = false) => {
    setHighlight(null);
    if (!additive) {
      const selected = tagFilters.length === 1 && tagFilters[0] === tag && sourceFilters.length === 0 && topicFilters.length === 0 && flagFilters.length === 0 && purposeFilters.length === 0;
      setTagFilters(selected ? [] : [tag]);
      setSourceFilters([]);
      setTopicFilters([]);
      setFlagFilters([]);
      setPurposeFilters([]);
      return;
    }
    setTagFilters((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const selectTopic = (topic: number, additive = false) => {
    setHighlight(null);
    if (!additive) {
      const selected = topicFilters.length === 1 && topicFilters[0] === topic && sourceFilters.length === 0 && tagFilters.length === 0 && flagFilters.length === 0 && purposeFilters.length === 0;
      setTopicFilters(selected ? [] : [topic]);
      setSourceFilters([]);
      setTagFilters([]);
      setFlagFilters([]);
      setPurposeFilters([]);
      return;
    }
    setTopicFilters((prev) => (prev.includes(topic) ? prev.filter((t) => t !== topic) : [...prev, topic]));
  };

  const toggleFlagFilter = (flag: string, additive = false) => {
    setHighlight(null);
    if (!additive) {
      const selected = flagFilters.length === 1 && flagFilters[0] === flag && sourceFilters.length === 0 && tagFilters.length === 0 && topicFilters.length === 0 && purposeFilters.length === 0;
      setFlagFilters(selected ? [] : [flag]);
      setSourceFilters([]);
      setTagFilters([]);
      setTopicFilters([]);
      setPurposeFilters([]);
      return;
    }
    setFlagFilters((prev) => (prev.includes(flag) ? prev.filter((f) => f !== flag) : [...prev, flag]));
  };

  const applyView = (v: { purposeFilters?: string[]; sourceFilters?: string[]; tagFilters?: string[]; flagFilters?: string[]; minScore?: number; minAgeDays?: number }) => {
    setHighlight(null);
    setFilterPreview(null);
    setPurposeFilters(v.purposeFilters ?? []);
    setSourceFilters(v.sourceFilters ?? []);
    setTagFilters(v.tagFilters ?? []);
    setTopicFilters([]);
    setFlagFilters(v.flagFilters ?? []);
    setMinScore(v.minScore ?? 0);
    setMinAgeDays(v.minAgeDays ?? 0);
  };

  const selectPurpose = (purpose: string, additive = false) => {
    setHighlight(null);
    if (!additive) {
      const selected = purposeFilters.length === 1 && purposeFilters[0] === purpose && sourceFilters.length === 0 && tagFilters.length === 0 && topicFilters.length === 0 && flagFilters.length === 0;
      setPurposeFilters(selected ? [] : [purpose]);
      setSourceFilters([]);
      setTagFilters([]);
      setTopicFilters([]);
      setFlagFilters([]);
      return;
    }
    setPurposeFilters((prev) => (prev.includes(purpose) ? prev.filter((p) => p !== purpose) : [...prev, purpose]));
  };

  const onRediscover = async (strategy: string) => {
    try {
      const res = await api.rediscovery(strategy);
      if (!res.items.length) {
        setToast(strategy === "on_this_day" ? "Nothing saved on this day yet." : "No forgotten gems right now.");
        return;
      }
      setHighlight(new Set(res.items.map((i) => i.id)));
      selectNote(res.items[0].id);
      setToast(`${res.items.length} ${strategy === "on_this_day" ? "from this day in the past" : "forgotten gem(s)"} — highlighted`);
    } catch (e) {
      setToast(String(e));
    }
  };

  const onShowRelated = (id: string) => {
    const neighbors = new Set<string>([id]);
    for (const e of graph?.edges ?? []) {
      if (e.source === id) neighbors.add(e.target);
      else if (e.target === id) neighbors.add(e.source);
    }
    setHighlight(neighbors);
  };

  const onAsk = async (question: string) => {
    setAsk({ open: true, question, result: null, loading: true });
    try {
      const result = await api.ask(question);
      setAsk((a) => ({ ...a, result, loading: false }));
    } catch (e) {
      setAsk((a) => ({ ...a, loading: false, result: { ok: false, answer: "", message: String(e), sources: [] } }));
    }
  };

  const onFind = async (q: string) => {
    setBusy(true);
    try {
      const res = await api.find(q);
      const searched = res.query || q;
      if (!res.configured) setToast("Semantic search is not configured.");
      else if (res.results.length === 0) setToast(`No matches for “${searched}”.`);
      else {
        // Light up every match in the graph (like a tag filter) instead of
        // jumping straight into the first hit.
        clearFanoutFilters();
        setHighlight(new Set(res.results.map((r) => r.id)));
        setToast(`${res.results.length} match${res.results.length === 1 ? "" : "es"} for “${searched}”`);
      }
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const DUP_REASON_LABEL: Record<string, string> = {
    source_url: "same URL",
    resolved_url: "same final URL",
    content_hash: "same content",
  };

  const onSave = async (url: string, force = false) => {
    setSaving(true);
    try {
      const res = await api.saveUrl(url, force);
      if (!res.created) {
        // Duplicate: offer a "save anyway" override rather than silently dropping it.
        const reason = res.duplicate_reason ? DUP_REASON_LABEL[res.duplicate_reason] ?? res.duplicate_reason : "duplicate";
        selectNote(res.note.id);
        if (window.confirm(`Already saved "${res.note.title}" (${reason}).\n\nSave a fresh copy anyway?`)) {
          setSaving(false);
          return onSave(url, true);
        }
        setToast(`Already saved (${reason})`);
        return;
      }
      await refreshData();
      selectNote(res.note.id);
      setToast(res.similar_note_id ? `Saved: ${res.note.title} (looks similar to an existing note)` : `Saved: ${res.note.title}`);
    } catch (e) {
      setToast(String(e));
    } finally {
      setSaving(false);
    }
  };

  // Idea topic follows the active filter: first tag -> first graph topic -> first source kind, else topic-less.
  const ideaTopic = (): string => {
    if (tagFilters[0]) return tagFilters[0];
    if (topicFilters[0] != null) return graph?.topic_labels?.[String(topicFilters[0])] ?? `topic ${topicFilters[0] + 1}`;
    return sourceFilters[0] ? srcLabel(sourceFilters[0]) : "";
  };

  const generateIdea = async () => {
    const topic = ideaTopic();
    setIdeaJob((j) => ({ ...j, status: "loading", topic }));
    try {
      // Project Mode: scope idea source-knowledge to the active purpose/tag filters.
      const res = await api.generateIdea(topic || undefined, flagFilters.includes("favorite"), {
        purpose: purposeFilters[0] ?? null,
        tags: tagFilters.length ? tagFilters : undefined,
      });
      if (!res.ok) {
        setToast(res.message);
        setIdeaJob((j) => ({ ...j, status: "idle" }));
        return;
      }
      setIdeaJob({ status: "ready", idea: res.idea, open: false, topic });
    } catch (e) {
      setToast(String(e));
      setIdeaJob((j) => ({ ...j, status: "idle" }));
    }
  };

  const onLightbulb = () => {
    if (ideaJob.status === "ready") setIdeaJob((j) => ({ ...j, open: true }));
    else if (ideaJob.status === "idle") generateIdea();
  };

  const onReprocess = async (id: string) => {
    setProcessingNotes((m) => ({ ...m, [id]: "reprocess" }));
    try {
      const res = await api.reprocess(id);
      setNote((current) => (selectedIdRef.current === id ? res.note : current));
      setToast(res.message);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      clearProcessing(id, "reprocess");
    }
  };

  const onRepersonalize = async (id: string) => {
    setProcessingNotes((m) => ({ ...m, [id]: "repersonalize" }));
    try {
      const res = await api.repersonalize(id);
      setNote((current) => (selectedIdRef.current === id ? res.note : current));
      setToast(res.message);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      clearProcessing(id, "repersonalize");
    }
  };

  const onResearch = async (id: string) => {
    setProcessingNotes((m) => ({ ...m, [id]: "research" }));
    try {
      const res = await api.research(id);
      setNote((current) => (selectedIdRef.current === id ? res.note : current));
      setToast(res.message);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      clearProcessing(id, "research");
    }
  };

  const onDelete = async (id: string) => {
    setPaneBusy(true);
    try {
      await api.deleteNote(id);
      deselect();
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

  const onEditTitle = async (id: string, title: string) => {
    setPaneBusy(true);
    try {
      const updated = await api.editTitle(id, title);
      setNote(updated);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onSetStatus = async (id: string, status: string) => {
    setPaneBusy(true);
    try {
      const updated = await api.setStatus(id, status);
      setNote(updated);
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onSetFavorite = async (id: string, value: boolean) => {
    setPaneBusy(true);
    try {
      const updated = await api.setFavorite(id, value);
      setNote(updated);
      await refreshData(); // node's favorite flag changed
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onSetPurpose = async (id: string, purpose: string | null) => {
    setPaneBusy(true);
    try {
      const updated = await api.setPurpose(id, purpose);
      setNote(updated);
      await refreshData(); // node purpose + inbox count changed
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  const onRate = async (id: string, rating: number) => {
    try {
      const updated = await api.rateIdea(id, rating);
      // Rating consumes the idea: drop the "ready" (yellow bulb) state.
      setIdeaJob((j) => ({ ...j, idea: updated, status: "idle" }));
    } catch (e) {
      setToast(String(e));
    }
  };

  const onOpenIdeaById = async (id: string) => {
    try {
      const idea = await api.idea(id);
      setIdeaJob({ status: "ready", idea, open: true, topic: idea.topic ?? "" });
    } catch (e) {
      setToast(String(e));
    }
  };

  const openProposals = async () => {
    setProposals((p) => ({ ...p, open: true, loading: true }));
    try {
      const pr = await api.proposals();
      setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending, loading: false }));
    } catch (e) {
      setToast(String(e));
      setProposals((p) => ({ ...p, loading: false }));
    }
  };

  const resolveProposal = async (id: string, action: "approve" | "reject") => {
    setProposals((p) => ({ ...p, busyId: id }));
    try {
      const res = action === "approve" ? await api.approveProposal(id) : await api.rejectProposal(id);
      setToast(res.message);
      const pr = await api.proposals();
      setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending, busyId: null }));
      if (action === "approve") await refreshData(); // a merge may have deleted a note
    } catch (e) {
      setToast(String(e));
      setProposals((p) => ({ ...p, busyId: null }));
    }
  };

  const runIngest = async () => {
    setProposals((p) => ({ ...p, runningJob: "ingest" }));
    try {
      const s = await api.runIngest();
      setToast(`Ingest: ${s.created} new, ${s.duplicates} dup, ${s.failed} failed (${s.feeds} feed${s.feeds === 1 ? "" : "s"})`);
      await refreshData();
    } catch (e) {
      setToast(String(e));
    } finally {
      setProposals((p) => ({ ...p, runningJob: null }));
    }
  };

  const openActivityLog = async () => {
    setActivity((a) => ({ ...a, open: true, loading: true }));
    try {
      const res = await api.activity();
      setActivity({ open: true, loading: false, items: res.items });
    } catch (e) {
      setToast(String(e));
      setActivity((a) => ({ ...a, loading: false }));
    }
  };

  const runTraverse = async () => {
    setProposals((p) => ({ ...p, runningJob: "traverse" }));
    setMaintenanceStatus(null);
    try {
      const s = await api.runTraverse();
      const status = await api.maintenanceStatus();
      setMaintenanceStatus(status);
      setToast(`Maintenance: links +${s.links_added}/-${s.links_removed}, ${s.tags_merged} tags merged, ${s.duplicates_proposed} new merge proposal(s)`);
      const pr = await api.proposals();
      setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending, runningJob: null }));
      await refreshData();
    } catch (e) {
      try {
        setMaintenanceStatus(await api.maintenanceStatus());
      } catch {
        /* ignore */
      }
      setToast(String(e));
      setProposals((p) => ({ ...p, runningJob: null }));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAsk((a) => ({ ...a, open: false }));
        setIdeaJob((j) => ({ ...j, open: false, status: "idle" }));
        setProposals((p) => ({ ...p, open: false }));
        setActivity((a) => ({ ...a, open: false }));
        setOpenFile(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (authed === null) {
    // Brief auth check; keep the dark canvas to avoid a white flash.
    return <div style={{ width: "100%", height: "100%", background: P.bg0 }} />;
  }
  if (authed === false) {
    return (
      <Login
        needsSetup={needsSetup}
        onAuthenticated={() => {
          setNeedsSetup(false);
          setAuthed(true);
        }}
      />
    );
  }

  return (
    <div style={{ width: "100%", height: "100%", background: P.bg0, color: P.hi, fontFamily: P.sans, display: "flex", flexDirection: "column" }}>
      <TopBar
        busy={busy || ask.loading}
        saving={saving}
        ideaStatus={ideaJob.status}
        inboxCount={stats?.notes.inbox ?? 0}
        inboxActive={flagFilters.includes("inbox")}
        onOpenInbox={() => toggleFlagFilter("inbox")}
        onAsk={onAsk}
        onFind={onFind}
        onSave={onSave}
        onLightbulb={onLightbulb}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
        <TreePane
          open={leftOpen}
          onToggle={() => setLeftOpen((o) => !o)}
          width={leftWidth}
          onResize={(w) => setLeftWidth(clamp(w, 200, 560))}
          tree={tree}
          noteKind={noteKind}
          selectedNoteId={selectedId}
          graph={graph}
          tags={tags}
          stats={stats}
          sourceFilters={sourceFilters}
          tagFilters={tagFilters}
          topicFilters={topicFilters}
          flagFilters={flagFilters}
          purposeFilters={purposeFilters}
          minAgeDays={minAgeDays}
          minScore={minScore}
          usage={usage}
          onSelectNote={selectNote}
          onOpenIdea={onOpenIdeaById}
          onOpenFile={setOpenFile}
          onSelectSource={selectSource}
          onSelectTag={selectTag}
          onSelectTopic={selectTopic}
          onToggleFlagFilter={toggleFlagFilter}
          onSelectPurpose={selectPurpose}
          onRediscover={onRediscover}
          onApplyView={applyView}
          currentView={{ purposeFilters, sourceFilters, tagFilters, flagFilters, minScore, minAgeDays }}
          onClearFilters={clearAllFilters}
          onMinAgeDays={setMinAgeDays}
          onMinScore={setMinScore}
          onTagsChanged={() => { refreshData().catch((e) => setToast(String(e))); }}
          onPreviewFilter={setFilterPreview}
        />
        <GraphPane
          graph={graph}
          sourceFilters={sourceFilters}
          tagFilters={tagFilters}
          topicFilters={topicFilters}
          flagFilters={flagFilters}
          purposeFilters={purposeFilters}
          minAgeDays={minAgeDays}
          minScore={minScore}
          selectedId={selectedId}
          highlightIds={highlight}
          previewIds={filterPreview}
          onSelect={selectNote}
          onDeselect={deselect}
          onClearHighlight={() => setHighlight(null)}
          onClearFilters={clearAllFilters}
          leftPanelWidth={leftOpen ? leftWidth : LEFT_CLOSED_W}
          processingNodeIds={processingNotes}
          maintenanceStatus={maintenanceStatus}
          maintenanceEvents={maintenanceStatus?.events ?? []}
        />
        <NotePane
          note={note}
          loading={noteLoading}
          busy={paneBusy || selectedAction != null}
          reprocessing={selectedAction === "reprocess"}
          repersonalizing={selectedAction === "repersonalize"}
          researching={selectedAction === "research"}
          open={rightOpen}
          onToggle={() => setRightOpen((o) => !o)}
          width={rightWidth}
          onResize={(w) => setRightWidth(clamp(w, 320, 680))}
          onSelectRelated={selectNote}
          onShowRelated={onShowRelated}
          onReprocess={onReprocess}
          onRepersonalize={onRepersonalize}
          onResearch={onResearch}
          onDelete={onDelete}
          onEditTags={onEditTags}
          onEditTitle={onEditTitle}
          onSetStatus={onSetStatus}
          onSetPurpose={onSetPurpose}
          onSelectTag={(tag) => selectTag(tag)}
          onSetFavorite={onSetFavorite}
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
        {ideaJob.open && (
          <IdeaView
            topic={ideaJob.topic}
            idea={ideaJob.idea}
            onClose={() => setIdeaJob((j) => ({ ...j, open: false, status: "idle" }))}
            onRate={onRate}
            onRegenerate={generateIdea}
          />
        )}
        {proposals.open && (
          <ProposalsOverlay
            proposals={proposals.items}
            loading={proposals.loading}
            busyId={proposals.busyId}
            onClose={() => setProposals((p) => ({ ...p, open: false }))}
            onApprove={(id) => resolveProposal(id, "approve")}
            onReject={(id) => resolveProposal(id, "reject")}
          />
        )}
        {activity.open && (
          <ActivityLog
            entries={activity.items}
            loading={activity.loading}
            onClose={() => setActivity((a) => ({ ...a, open: false }))}
          />
        )}
        {openFile && <FileViewer file={openFile} onClose={() => setOpenFile(null)} />}
        {settingsOpen && (
          <SettingsOverlay
            onClose={() => setSettingsOpen(false)}
            onPullFeeds={runIngest}
            ingesting={proposals.runningJob === "ingest"}
            pendingProposals={proposals.pending}
            maintaining={proposals.runningJob === "traverse"}
            onRunMaintenance={runTraverse}
            onReviewProposals={openProposals}
            onOpenLog={openActivityLog}
            onLogout={onLogout}
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
