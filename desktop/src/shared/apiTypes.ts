/** Shapes of backend responses used by the renderer. They mirror the Python API in backend/mathengine/api/routes.py. */

export type Verdict = "correct" | "incorrect" | "invalid_input" | "unverifiable";
export type VerificationStatus = "ai_draft" | "reviewed" | "verified";

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  knowledge: {
    index_built: boolean;
    concept_count: number; // reviewed and verified concepts only
    excluded_draft_count: number; // unreviewed AI drafts kept out of the authoritative index
    developer_preview_built: boolean; // whether developer mode can load drafts
    error: string | null;
  };
}

export interface OllamaStatusResponse {
  reachable: boolean;
  model: string;
  model_installed: boolean;
  installed_models: string[];
  error: string | null;
}

export interface SubjectsResponse {
  subjects: { subject: string; concept_count: number }[];
}

export interface SearchHit {
  concept_id: string;
  title: string;
  subject: string;
  topic: string;
  score: number;
  exact: boolean;
  matched_terms: string[];
  verification_status: VerificationStatus;
}

export interface SearchResponse {
  query: string;
  status: "listing" | "matches" | "ambiguous" | "insufficient" | "needs_clarification";
  message: string;
  hits: SearchHit[];
}

export interface PublicExercise {
  id: string;
  prompt: string;
  answer_type: "number" | "expression" | "equation_solution";
  hint_count: number;
}

export interface ConceptSummary {
  id: string;
  title: string;
  subject: string;
  topic: string;
  subtopic: string | null;
  difficulty: number;
  summary: string;
  verification_status: VerificationStatus;
  is_draft: boolean;
}

export interface ConceptDetail {
  id: string;
  title: string;
  aliases: string[];
  subject: string;
  topic: string;
  subtopic: string | null;
  difficulty: number;
  summary: string;
  definition: string;
  explanations: { level: "intro" | "standard" | "advanced"; text: string }[];
  formulas: { name: string; expression: string; result: string | null; conditions: string[] }[];
  worked_examples: { title: string; problem: string; steps: string[]; answer: string }[];
  misconceptions: { description: string; explanation: string; correction: string }[];
  exercises: PublicExercise[];
  prerequisites: ConceptSummary[];
  related: ConceptSummary[];
  sources: { title: string; kind: string; url: string | null }[];
  verification: { status: VerificationStatus; reviewed_by: string | null; reviewed_on: string | null; notes: string };
  version: string;
}

export interface CheckResponse {
  verdict: Verdict;
  verified: boolean;
  method: string;
  message: string;
  feedback: string;
  attempt_id: number;
}

export interface HintResponse {
  hint_index: number;
  hint_count: number;
  has_more: boolean;
  hint: string;
}
