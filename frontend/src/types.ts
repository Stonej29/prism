export interface NoteSummary {
  id: string;
  title: string;
  summary: string;
  source_url: string;
  source_kind: string;
  date_saved: string;
  tags: string[];
  overall: number | null;
  llm_status: string;
}

export interface RelatedNote {
  id: string;
  title: string;
  reason: string;
  path: string;
  origin: "auto" | "llm" | "manual" | "unknown" | string;
}

export interface NoteDetail {
  id: string;
  title: string;
  summary: string;
  source_url: string;
  resolved_url: string;
  source_kind: string;
  date_saved: string;
  fetched_at: string | null;
  status: string;
  fetch_status: string;
  llm_status: string;
  llm_model: string | null;
  embedding_status: string;
  embedding_dimensions: number | null;
  research_status: string | null;
  researched_at: string | null;
  research_error: string | null;
  research_sources: { url: string; title: string }[];
  scores: Record<string, number>;
  tags: string[];
  structured_summary: Record<string, unknown>;
  related_notes: RelatedNote[];
  favorite: boolean;
}

export interface GraphNode {
  id: string;
  title: string;
  source_kind: string;
  status: string;
  date_saved: string;
  overall: number | null;
  favorite: boolean;
  failed: boolean;
  tags: string[];
  topic: number;
  community: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  reason: string;
  origin: "auto" | "llm" | "manual" | "unknown" | string;
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
  topic_labels: Record<string, string>;
  counts: { notes: number; links: number; topics: number; communities: number; links_by_origin?: Record<string, number> };
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface TreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  children?: TreeNode[];
  note_id?: string | null;
  idea_id?: string | null;
  root?: "vault" | "archive";
}

export interface Stats {
  notes: {
    total: number;
    llm_generated: number;
    llm_failed: number;
    llm_skipped: number;
    embedding_indexed: number;
    embedding_failed: number;
    embedding_skipped: number;
    unreviewed: number;
    reviewed: number;
    archived: number;
  };
  tags: number;
  index_configured: boolean;
  embedding_model: string | null;
  llm_configured: boolean;
  llm_model: string | null;
}

export interface Usage {
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
  today_total_tokens: number;
  today_calls: number;
}

export interface Candidate {
  id: string;
  title: string;
  summary: string;
  source_url: string;
  path: string;
  tags: string[];
  score: number;
}

export interface AskResult {
  ok: boolean;
  answer: string;
  message: string;
  sources: Candidate[];
}

export interface Idea {
  id: string;
  title: string;
  summary: string;
  topic: string | null;
  created_at: string;
  rating: number | null;
  rated_at: string | null;
  llm_status: string;
  llm_model: string | null;
  tags: string[];
  source_note_ids: string[];
  structured: Record<string, unknown>;
}

export interface IdeaResult {
  ok: boolean;
  message: string;
  idea: Idea | null;
}

export interface Proposal {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  note_ids: string[];
  payload: Record<string, unknown>;
  description: string;
}

export interface ProposalList {
  items: Proposal[];
  pending: number;
  limit: number;
  offset: number;
}

export interface ProposalAction {
  ok: boolean;
  message: string;
  proposal: Proposal | null;
}

export interface IngestSummary {
  ok: boolean;
  feeds_configured: number;
  feeds: number;
  seen: number;
  created: number;
  duplicates: number;
  failed: number;
  errors: string[];
}

export interface TraverseSummary {
  ok: boolean;
  notes: number;
  links_added: number;
  links_removed: number;
  notes_relinked: number;
  tags_merged: number;
  notes_retagged: number;
  duplicates_proposed: number;
  pending_proposals: number;
  settings?: MaintenanceSettings;
  links_by_origin_before?: Record<string, number>;
  links_by_origin_after?: Record<string, number>;
}

export interface MaintenanceSettings {
  link_threshold: number;
  max_links_per_note: number;
  max_auto_links: number;
  dup_threshold: number;
}

export interface MaintenanceEvent {
  seq: number;
  at: string;
  kind: string;
  phase?: string;
  message?: string;
  note_id?: string;
  source?: string;
  target?: string;
  proposal_id?: string;
  keep?: string;
  remove?: string;
  similarity?: number;
  links_added?: number;
  links_removed?: number;
  tags?: string[];
  origin?: string;
  settings?: MaintenanceSettings;
  counts?: Record<string, number>;
}

export interface ActivityEntry {
  id: number;
  at: string;
  action: string;
  status: string;
  message: string;
  details: Record<string, unknown>;
}

export interface ActivityPayload {
  items: ActivityEntry[];
  limit: number;
}

export interface MaintenanceStatus {
  status: "idle" | "running" | "complete" | "failed" | string;
  run_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_seq: number;
  events: MaintenanceEvent[];
  event_count: number;
  summary: TraverseSummary | null;
  error: string | null;
}
