/**
 * Allowlist of backend routes the renderer may reach.
 *
 * The renderer never talks to the network directly. It asks the Electron main process, which
 * checks each request against this list before forwarding it to the local Python backend.
 * Anything not listed here is refused, so a compromised page cannot reach arbitrary endpoints.
 */

export type HttpMethod = "GET" | "POST";

export interface BackendRequest {
  method: HttpMethod;
  path: string;
  body?: unknown;
}

export interface BackendResponse {
  ok: boolean;
  status: number;
  data: unknown;
  error?: string;
}

export const MAX_BODY_BYTES = 16 * 1024;
export const MAX_PATH_LENGTH = 512;

interface Route {
  method: HttpMethod;
  pattern: RegExp;
}

// Query strings are limited to characters that URLSearchParams produces. Concept ids cannot
// contain "/" or ".." segments, so a path cannot escape its route.
const QUERY = String.raw`(\?[A-Za-z0-9_=&%+.\-]*)?`;
const CONCEPT_ID = String.raw`[a-z][a-z0-9_]*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+`;

export const ALLOWED_ROUTES: readonly Route[] = [
  { method: "GET", pattern: new RegExp(`^/api/health${QUERY}$`) },
  { method: "GET", pattern: new RegExp(`^/api/ollama/status${QUERY}$`) },
  { method: "GET", pattern: new RegExp(`^/api/subjects${QUERY}$`) },
  { method: "GET", pattern: new RegExp(`^/api/concepts${QUERY}$`) },
  { method: "GET", pattern: new RegExp(`^/api/concepts/${CONCEPT_ID}${QUERY}$`) },
  { method: "GET", pattern: new RegExp(`^/api/progress/summary${QUERY}$`) },
  { method: "POST", pattern: /^\/api\/exercises\/(check|hint)$/ },
  { method: "POST", pattern: /^\/api\/math\/evaluate$/ },
];

export function isAllowedRoute(method: string, path: string): boolean {
  return ALLOWED_ROUTES.some((route) => route.method === method && route.pattern.test(path));
}

export class InvalidRequestError extends Error {}

/** Validate an untrusted payload from the renderer. Throws InvalidRequestError when it is not acceptable. */
export function validateRequest(payload: unknown): BackendRequest {
  if (typeof payload !== "object" || payload === null) {
    throw new InvalidRequestError("The request must be an object.");
  }
  const { method, path, body } = payload as Record<string, unknown>;
  if (method !== "GET" && method !== "POST") {
    throw new InvalidRequestError("Only GET and POST requests are allowed.");
  }
  if (typeof path !== "string" || path.length > MAX_PATH_LENGTH) {
    throw new InvalidRequestError("The path is missing or too long.");
  }
  if (!isAllowedRoute(method, path)) {
    throw new InvalidRequestError(`The route ${method} ${path} is not allowed.`);
  }
  if (body !== undefined) {
    if (method === "GET") {
      throw new InvalidRequestError("GET requests cannot have a body.");
    }
    const serialized = JSON.stringify(body) ?? "";
    if (new TextEncoder().encode(serialized).length > MAX_BODY_BYTES) {
      throw new InvalidRequestError("The request body is too large.");
    }
  }
  return { method, path, body };
}
