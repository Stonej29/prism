import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { P, srcLabel } from "./theme";
import type { AskResult, GraphPayload, Idea, NoteDetail, Proposal, Stats, TagCount, TreeNode } from "./types";
import { TopBar } from "./components/TopBar";
import { TreePane } from "./components/TreePane";
import { GraphPane } from "./components/GraphPane";
import { NotePane } from "./components/NotePane";
import { AskOverlay } from "./components/AskOverlay";
import { ProposalsOverlay } from "./components/ProposalsOverlay";
import { IdeaView } from "./components/IdeaView";
import { FileViewer, type OpenFile } from "./components/FileViewer";
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

const LEFT_CLOSED_W = 32;
const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

export default function App() {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [paneBusy, setPaneBusy] = useState(false);

  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(false);
  const [leftWidth, setLeftWidth] = useState(264);
  const [rightWidth, setRightWidth] = useState(392);

  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Set<string> | null>(null);

  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ask, setAsk] = useState<AskState>({ open: false, question: "", result: null, loading: false });
  const [ideaJob, setIdeaJob] = useState<IdeaJob>({ status: "idle", idea: null, open: false, topic: "" });
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [proposals, setProposals] = useState<ProposalsState>({ open: false, items: [], pending: 0, loading: false, busyId: null, runningJob: null });

  const noteKind = useMemo(() => {
    const m: Record<string, string> = {};
    for (const n of graph?.nodes ?? []) m[n.id] = n.source_kind;
    return m;
  }, [graph]);

  const refreshData = useCallback(async () => {
    const [g, t, s, tr, pr] = await Promise.all([api.graph(), api.tags(), api.stats(), api.tree(), api.proposals()]);
    setGraph(g);
    setTags(t.items);
    setStats(s);
    setTree(tr);
    setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending }));
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

  const onShowRelated = (id: string) => {
    const neighbors = new Set<string>([id]);
    for (const e of graph?.edges ?? []) {
      if (e.source === id) neighbors.add(e.target);
      else if (e.target === id) neighbors.add(e.source);
    }
    setHighlight(neighbors);
  };

  // Inbox: highlight unreviewed notes in the graph (clearing re-clicks).
  const onInbox = () => {
    const unreviewed = new Set((graph?.nodes ?? []).filter((n) => n.status === "unreviewed").map((n) => n.id));
    setHighlight((cur) => (cur && cur.size === unreviewed.size && [...unreviewed].every((id) => cur.has(id)) ? null : unreviewed));
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
      if (!res.configured) setToast("Semantic search is not configured.");
      else if (res.results.length === 0) setToast(`No matches for “${q}”.`);
      else selectNote(res.results[0].id);
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onSave = async (url: string) => {
    setSaving(true);
    try {
      const res = await api.saveUrl(url);
      await refreshData();
      selectNote(res.note.id);
      setToast(res.created ? `Saved: ${res.note.title}` : `Already saved (${res.duplicate_reason})`);
    } catch (e) {
      setToast(String(e));
    } finally {
      setSaving(false);
    }
  };

  // Idea topic follows the active filter: tag → source kind, else topic-less.
  const ideaTopic = (): string => activeTag || (sourceFilter ? srcLabel(sourceFilter) : "");

  const generateIdea = async () => {
    const topic = ideaTopic();
    setIdeaJob((j) => ({ ...j, status: "loading", topic }));
    try {
      const res = await api.generateIdea(topic || undefined);
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

  const onSetJobFlag = async (id: string, value: boolean) => {
    setPaneBusy(true);
    try {
      const updated = await api.setJobFlag(id, value);
      setNote(updated);
      await refreshData(); // node's job_relevant flag changed
    } catch (e) {
      setToast(String(e));
    } finally {
      setPaneBusy(false);
    }
  };

  // Job: highlight job-relevant notes in the graph (clearing re-clicks).
  const onJob = () => {
    const flagged = new Set((graph?.nodes ?? []).filter((n) => n.job_relevant).map((n) => n.id));
    if (flagged.size === 0) {
      setToast("No notes flagged as job-relevant yet (use the ☆ on a note).");
      return;
    }
    setHighlight((cur) => (cur && cur.size === flagged.size && [...flagged].every((id) => cur.has(id)) ? null : flagged));
  };

  const onRate = async (id: string, rating: number) => {
    try {
      const updated = await api.rateIdea(id, rating);
      setIdeaJob((j) => ({ ...j, idea: updated }));
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

  const runTraverse = async () => {
    setProposals((p) => ({ ...p, runningJob: "traverse" }));
    try {
      const s = await api.runTraverse();
      setToast(`Maintenance: links +${s.links_added}/-${s.links_removed}, ${s.tags_merged} tags merged, ${s.duplicates_proposed} new merge proposal(s)`);
      const pr = await api.proposals();
      setProposals((p) => ({ ...p, items: pr.items, pending: pr.pending, runningJob: null }));
      await refreshData();
    } catch (e) {
      setToast(String(e));
      setProposals((p) => ({ ...p, runningJob: null }));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAsk((a) => ({ ...a, open: false }));
        setIdeaJob((j) => ({ ...j, open: false }));
        setProposals((p) => ({ ...p, open: false }));
        setOpenFile(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", background: P.bg0, color: P.hi, fontFamily: P.sans, display: "flex", flexDirection: "column" }}>
      <TopBar
        busy={busy || ask.loading}
        saving={saving}
        ideaStatus={ideaJob.status}
        pendingProposals={proposals.pending}
        unreviewed={stats?.notes.unreviewed ?? 0}
        ingesting={proposals.runningJob === "ingest"}
        maintaining={proposals.runningJob === "traverse"}
        onAsk={onAsk}
        onFind={onFind}
        onSave={onSave}
        onLightbulb={onLightbulb}
        onInbox={onInbox}
        onProposals={openProposals}
        onPullFeeds={runIngest}
        onRunMaintenance={runTraverse}
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
          sourceFilter={sourceFilter}
          activeTag={activeTag}
          onSelectNote={selectNote}
          onOpenIdea={onOpenIdeaById}
          onOpenFile={setOpenFile}
          onSelectSource={onSelectSource}
          onSelectTag={onSelectTag}
          onJob={onJob}
        />
        <GraphPane
          graph={graph}
          sourceFilter={sourceFilter}
          onSourceFilter={onSelectSource}
          selectedId={selectedId}
          highlightIds={highlight}
          onSelect={selectNote}
          onDeselect={deselect}
          onClearHighlight={() => setHighlight(null)}
          leftPanelWidth={leftOpen ? leftWidth : LEFT_CLOSED_W}
        />
        <NotePane
          note={note}
          loading={noteLoading}
          busy={paneBusy}
          open={rightOpen}
          onToggle={() => setRightOpen((o) => !o)}
          width={rightWidth}
          onResize={(w) => setRightWidth(clamp(w, 320, 680))}
          onSelectRelated={selectNote}
          onShowRelated={onShowRelated}
          onReprocess={onReprocess}
          onDelete={onDelete}
          onEditTags={onEditTags}
          onEditTitle={onEditTitle}
          onSetStatus={onSetStatus}
          onSetJobFlag={onSetJobFlag}
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
            onClose={() => setIdeaJob((j) => ({ ...j, open: false }))}
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
        {openFile && <FileViewer file={openFile} onClose={() => setOpenFile(null)} />}
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
