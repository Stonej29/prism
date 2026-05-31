import type {
  AskResult,
  Candidate,
  GraphPayload,
  Idea,
  IdeaResult,
  NoteDetail,
  IngestSummary,
  NoteSummary,
  Proposal,
  ProposalAction,
  ProposalList,
  MaintenanceSettings,
  Stats,
  TagCount,
  TraverseSummary,
  TreeNode,
  Usage,
} from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  graph: (source?: string) =>
    req<GraphPayload>(`/graph${source ? `?source=${encodeURIComponent(source)}` : ""}`),

  notes: (params: { source?: string; tag?: string; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.source) q.set("source", params.source);
    if (params.tag) q.set("tag", params.tag);
    if (params.limit != null) q.set("limit", String(params.limit));
    if (params.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return req<{ items: NoteSummary[]; limit: number; offset: number }>(`/notes${qs ? `?${qs}` : ""}`);
  },

  note: (id: string) => req<NoteDetail>(`/notes/${id}`),

  saveUrl: (url: string) =>
    req<{ created: boolean; duplicate_reason: string | null; note: NoteDetail }>(`/notes`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  reprocess: (id: string) =>
    req<{ ok: boolean; message: string; note: NoteDetail }>(`/notes/${id}/reprocess`, { method: "POST" }),

  retryFailed: () =>
    req<{ total: number; retried: number; repaired: number; failed: number; skipped: number; messages: string[] }>(
      `/notes/retry-failed`,
      { method: "POST" },
    ),

  deleteNote: (id: string) => req<{ ok: boolean; message: string }>(`/notes/${id}`, { method: "DELETE" }),

  editTags: (id: string, tags: string[]) =>
    req<NoteDetail>(`/notes/${id}/tags`, { method: "PUT", body: JSON.stringify({ tags }) }),

  editTitle: (id: string, title: string) =>
    req<NoteDetail>(`/notes/${id}/title`, { method: "PUT", body: JSON.stringify({ title }) }),

  setStatus: (id: string, status: string) =>
    req<NoteDetail>(`/notes/${id}/status`, { method: "PUT", body: JSON.stringify({ status }) }),

  setJobFlag: (id: string, value: boolean) =>
    req<NoteDetail>(`/notes/${id}/job_flag`, { method: "PUT", body: JSON.stringify({ value }) }),

  setStatusBulk: (ids: string[], status: string) =>
    req<{ status: string; results: { id: string; ok: boolean; status?: string }[] }>(`/notes/status`, {
      method: "PUT",
      body: JSON.stringify({ ids, status }),
    }),

  tags: () => req<{ items: TagCount[] }>(`/tags`),

  tree: () => req<TreeNode>(`/tree`),

  idea: (id: string) => req<Idea>(`/ideas/${id}`),

  fileUrl: (root: string, path: string) => `/api/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`,

  fileText: async (root: string, path: string): Promise<string> => {
    const res = await fetch(`/api/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.text();
  },

  stats: () => req<Stats>(`/stats`),

  usage: () => req<Usage>(`/usage`),

  find: (q: string, limit = 20) =>
    req<{ results: Candidate[]; configured: boolean; error?: string }>(
      `/find?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  ask: (question: string, limit = 6) =>
    req<AskResult>(`/ask`, { method: "POST", body: JSON.stringify({ question, limit }) }),

  ideas: () => req<{ items: Idea[] }>(`/ideas`),

  generateIdea: (topic?: string, preferJob = false) =>
    req<IdeaResult>(`/ideas`, { method: "POST", body: JSON.stringify({ topic: topic || null, prefer_job: preferJob }) }),

  rateIdea: (id: string, rating: number) =>
    req<Idea>(`/ideas/${id}/rating`, { method: "POST", body: JSON.stringify({ rating }) }),

  deleteIdea: (id: string) => req<{ ok: boolean; title: string }>(`/ideas/${id}`, { method: "DELETE" }),

  proposals: (status = "pending") =>
    req<ProposalList>(`/proposals?status=${encodeURIComponent(status)}`),

  approveProposal: (id: string) =>
    req<ProposalAction>(`/proposals/${id}/approve`, { method: "POST" }),

  rejectProposal: (id: string) =>
    req<ProposalAction>(`/proposals/${id}/reject`, { method: "POST" }),

  runIngest: () => req<IngestSummary>(`/maintenance/ingest`, { method: "POST" }),

  runTraverse: () => req<TraverseSummary>(`/maintenance/traverse`, { method: "POST" }),

  maintenanceSettings: () => req<MaintenanceSettings>(`/maintenance/settings`),

  saveMaintenanceSettings: (body: MaintenanceSettings) =>
    req<MaintenanceSettings>(`/maintenance/settings`, { method: "PUT", body: JSON.stringify(body) }),
};

export type { Proposal };
