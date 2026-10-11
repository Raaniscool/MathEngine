/**
 * Typed wrappers around the backend API. The renderer has no network access of its own:
 * every call goes through window.mathengine.request, which the main process validates.
 */
import type { BackendResponse } from "../../shared/backendRoutes";
import type {
  CheckResponse,
  ConceptDetail,
  HealthResponse,
  HintResponse,
  OllamaStatusResponse,
  SearchResponse,
  SubjectsResponse,
} from "../../shared/apiTypes";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type QueryValue = string | number | boolean | null | undefined;

/** Build a query string, skipping empty values. Returns "" when there is nothing to send. */
export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** A readable message for a failed backend call. */
export function describeFailure(response: BackendResponse): string {
  if (response.error) return response.error;
  const detail = (response.data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `The backend returned HTTP ${response.status}.`;
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await window.mathengine.request(body === undefined ? { method, path } : { method, path, body });
  if (!response.ok) {
    throw new ApiError(describeFailure(response), response.status);
  }
  return response.data as T;
}

export const api = {
  health: () => call<HealthResponse>("GET", "/api/health"),
  ollamaStatus: () => call<OllamaStatusResponse>("GET", "/api/ollama/status"),
  subjects: (includeDrafts: boolean) =>
    call<SubjectsResponse>("GET", `/api/subjects${buildQuery({ include_drafts: includeDrafts })}`),
  search: (query: string, options: { subject?: string; includeDrafts: boolean }) =>
    call<SearchResponse>(
      "GET",
      `/api/concepts${buildQuery({ q: query, subject: options.subject, include_drafts: options.includeDrafts })}`,
    ),
  concept: (conceptId: string, includeDrafts: boolean) =>
    call<ConceptDetail>(
      "GET",
      `/api/concepts/${encodeURIComponent(conceptId)}${buildQuery({ include_drafts: includeDrafts })}`,
    ),
  checkAnswer: (conceptId: string, exerciseId: string, answer: string, includeDrafts: boolean) =>
    call<CheckResponse>("POST", "/api/exercises/check", {
      concept_id: conceptId,
      exercise_id: exerciseId,
      answer,
      include_drafts: includeDrafts,
    }),
  hint: (conceptId: string, exerciseId: string, index: number, includeDrafts: boolean) =>
    call<HintResponse>("POST", "/api/exercises/hint", {
      concept_id: conceptId,
      exercise_id: exerciseId,
      index,
      include_drafts: includeDrafts,
    }),
};
