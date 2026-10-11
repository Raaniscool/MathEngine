/**
 * Forwards validated renderer requests to the local Python backend.
 *
 * Kept free of Electron imports so it can be unit-tested with a fake fetch.
 */
import { type BackendRequest, type BackendResponse, validateRequest } from "../shared/backendRoutes";

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const REQUEST_TIMEOUT_MS = 10_000;

/**
 * Resolve the backend base URL. Only plain-http loopback addresses are accepted, so the
 * knowledge engine can never be pointed at a remote server by configuration mistakes.
 */
export function resolveBackendUrl(configured: string | undefined): string {
  const candidate = configured?.trim() || DEFAULT_BACKEND_URL;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    throw new Error(`MATHENGINE_BACKEND_URL is not a valid URL: ${candidate}`);
  }
  const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost";
  if (url.protocol !== "http:" || !loopback) {
    throw new Error("MATHENGINE_BACKEND_URL must be an http:// address on 127.0.0.1 or localhost.");
  }
  return url.origin;
}

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

export async function forwardRequest(
  payload: unknown,
  baseUrl: string,
  fetchImpl: FetchLike = fetch,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<BackendResponse> {
  let request: BackendRequest;
  try {
    request = validateRequest(payload);
  } catch (error) {
    return { ok: false, status: 400, data: null, error: (error as Error).message };
  }

  const init: RequestInit = {
    method: request.method,
    headers: request.body === undefined ? { Accept: "application/json" } : { "Content-Type": "application/json", Accept: "application/json" },
    body: request.body === undefined ? undefined : JSON.stringify(request.body),
    signal: AbortSignal.timeout(timeoutMs),
  };

  try {
    const response = await fetchImpl(`${baseUrl}${request.path}`, init);
    const text = await response.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    const reason = (error as Error).name === "TimeoutError" ? "timed out" : "is not reachable";
    return {
      ok: false,
      status: 0,
      data: null,
      error: `The MathEngine backend ${reason} at ${baseUrl}. Start it first (see README: "Run the backend").`,
    };
  }
}
