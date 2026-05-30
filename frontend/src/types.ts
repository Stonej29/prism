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
  scores: Record<string, number>;
  tags: string[];
  structured_summary: Record<string, unknown>;
  related_notes: RelatedNote[];
}

export interface GraphNode {
  id: string;
  title: string;
  source_kind: string;
  overall: number | null;
  tags: string[];
  topic: number;
  community: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  reason: string;
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
  topic_labels: Record<string, string>;
  counts: { notes: number; links: number; topics: number; communities: number };
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
  };
  tags: number;
  index_configured: boolean;
  embedding_model: string | null;
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
