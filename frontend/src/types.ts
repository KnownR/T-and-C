export type SeverityLevel = "red" | "yellow" | "info";

export type UnfairCategory =
  | "arbitration"
  | "unilateral_change"
  | "content_removal"
  | "jurisdiction"
  | "choice_of_law"
  | "limitation_of_liability"
  | "unilateral_termination"
  | "contract_by_using";

export interface SpanModel {
  text: string;
  page: number;
  bbox?: [number, number, number, number] | null;
  font_size?: number | null;
  font_name?: string | null;
  is_bold: boolean;
}

export interface ClauseModel {
  id: string;
  document_id: string;
  ordinal: number;
  label?: string | null;
  heading?: string | null;
  text: string;
  page?: number | null;
  bboxes: number[][];
  char_start?: number | null;
  char_end?: number | null;
}

export interface DocumentResponse {
  id: string;
  filename?: string | null;
  source_type: "pdf" | "text";
  sha256?: string | null;
  page_count: number;
  raw_text: string;
  spans: SpanModel[];
  clauses: ClauseModel[];
  status: "parsed" | "analyzing" | "analyzed" | "failed";
  created_at: string;
}

export interface FindingModel {
  id: string;
  document_id: string;
  analysis_run_id?: string | null;
  category: UnfairCategory | string;
  severity: SeverityLevel;
  title: string;
  explanation: string;
  clause_id: string;
  quote: string;
  verification_status: "verified" | "verified_fuzzy" | "reanchored" | "rejected" | string;
  verification_details?: string | null;
  match_score?: number | null;
}

export interface AnalysisRunModel {
  id: string;
  document_id: string;
  model?: string | null;
  lens: string;
  total_clauses: number;
  tokens_in: number;
  tokens_out: number;
  proposed_count: number;
  verified_count: number;
  rejected_count: number;
  grounding_rate: number;
  latency_ms: number;
  cost_usd: number;
  created_at: string;
}

export interface AnalysisResponse {
  run: AnalysisRunModel;
  findings: FindingModel[];
}
