import type {
  ActivityPayload,
  AskResult,
  Candidate,
  GraphPayload,
  Idea,
  IdeaResult,
  NoteDetail,
  IngestSummary,
  MaintenanceStatus,
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

// Lets the app bounce back to the login screen if a session expires mid-use.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) onUnauthorized?.();
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

  research: (id: string) =>
    req<{ ok: boolean; message: string; note: NoteDetail }>(`/notes/${id}/research`, { method: "POST" }),

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

  setFavorite: (id: string, value: boolean) =>
    req<NoteDetail>(`/notes/${id}/favorite`, { method: "PUT", body: JSON.stringify({ value }) }),

  setStatusBulk: (ids: string[], status: string) =>
    req<{ status: string; results: { id: string; ok: boolean; status?: string }[] }>(`/notes/status`, {
      method: "PUT",
      body: JSON.stringify({ ids, status }),
    }),

  tags: () => req<{ items: TagCount[] }>(`/tags`),

  deleteTag: (tag: string) =>
    req<{ ok: boolean; tag: string; notes_updated: number }>(`/tags/${encodeURIComponent(tag)}`, { method: "DELETE" }),

  mergeTags: (source: string, target: string) =>
    req<{ ok: boolean; notes_updated: number }>(`/tags/merge`, { method: "POST", body: JSON.stringify({ source, target }) }),

  getProfile: () => req<{ content: string }>(`/profile`),

  saveProfile: (content: string) =>
    req<{ ok: boolean; content: string }>(`/profile`, { method: "PUT", body: JSON.stringify({ content }) }),

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

  find: (q: string, limit?: number) => {
    const params = new URLSearchParams({ q });
    if (limit != null) params.set("limit", String(limit));
    return req<{ results: Candidate[]; configured: boolean; query: string; limit: number; error?: string }>(`/find?${params.toString()}`);
  },

  ask: (question: string, limit = 6) =>
    req<AskResult>(`/ask`, { method: "POST", body: JSON.stringify({ question, limit }) }),

  ideas: () => req<{ items: Idea[] }>(`/ideas`),

  generateIdea: (topic?: string, preferFavorite = false) =>
    req<IdeaResult>(`/ideas`, { method: "POST", body: JSON.stringify({ topic: topic || null, prefer_favorite: preferFavorite }) }),

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

  maintenanceStatus: () => req<MaintenanceStatus>(`/maintenance/status`),

  runTraverse: () => req<TraverseSummary>(`/maintenance/traverse`, { method: "POST" }),

  maintenanceSettings: () => req<MaintenanceSettings>(`/maintenance/settings`),

  saveMaintenanceSettings: (body: MaintenanceSettings) =>
    req<MaintenanceSettings>(`/maintenance/settings`, { method: "PUT", body: JSON.stringify(body) }),

  activity: () => req<ActivityPayload>(`/activity`),

  authStatus: () =>
    req<{ auth_required: boolean; authenticated: boolean; needs_setup: boolean; env_locked: boolean }>(`/auth/status`),

  setupAccount: (username: string, password: string) =>
    req<{ ok?: boolean; authenticated: boolean }>(`/auth/setup`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  login: (username: string, password: string) =>
    req<{ ok?: boolean; authenticated: boolean }>(`/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  logout: () => req<{ ok: boolean; authenticated: boolean }>(`/auth/logout`, { method: "POST" }),

  changePassword: (current_password: string, new_password: string) =>
    req<{ ok: boolean; authenticated: boolean }>(`/auth/change-password`, {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  getSettings: () => req<SettingsConfig>(`/settings`),

  saveSettings: (body: SettingsUpdate) =>
    req<SettingsConfig>(`/settings`, { method: "PUT", body: JSON.stringify(body) }),
};

export interface SettingsField {
  value: string;
  source: "env" | "store" | "unset";
  locked: boolean;
}
export interface SettingsSecret {
  configured: boolean;
  source: "env" | "store" | "unset";
  locked: boolean;
}
export interface SettingsConfig {
  llm: { configured: boolean; base_url: SettingsField; model: SettingsField; api_key: SettingsSecret };
  embedding: { configured: boolean; base_url: SettingsField; model: SettingsField; api_key: SettingsSecret };
  telegram: { configured: boolean; allowed_user_ids: SettingsField; bot_token: SettingsSecret; applies_on_restart: boolean };
}
export type SettingsUpdate = Partial<{
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
  embedding_base_url: string;
  embedding_api_key: string;
  embedding_model: string;
  telegram_bot_token: string;
  telegram_allowed_user_ids: string;
}>;

export type { Proposal };
