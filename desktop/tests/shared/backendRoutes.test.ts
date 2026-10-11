import { describe, expect, it } from "vitest";
import { InvalidRequestError, isAllowedRoute, validateRequest } from "../../src/shared/backendRoutes";

describe("route allowlist", () => {
  it.each([
    ["GET", "/api/health"],
    ["GET", "/api/ollama/status"],
    ["GET", "/api/subjects?include_drafts=false"],
    ["GET", "/api/concepts?q=power+rule&limit=5"],
    ["GET", "/api/concepts/calculus.derivatives.power-rule?include_drafts=true"],
    ["POST", "/api/exercises/check"],
    ["POST", "/api/exercises/hint"],
    ["POST", "/api/math/evaluate"],
  ])("allows %s %s", (method, path) => {
    expect(isAllowedRoute(method, path)).toBe(true);
  });

  it.each([
    ["POST", "/api/knowledge/reload"], // admin route is not exposed to the page
    ["POST", "/api/actions/search_knowledge"], // the AI action route is not exposed to the page
    ["GET", "/api/exercises/check"], // method mismatch
    ["GET", "/api/concepts/../../secret"],
    ["GET", "/api/concepts/arithmetic..x"],
    ["GET", "/api/concepts/Arithmetic.Facts"],
    ["GET", "/api/concepts/arithmetic.facts/extra"],
    ["GET", "/file:///etc/passwd"],
    ["GET", "http://example.com/api/health"],
    ["DELETE", "/api/health"],
  ])("refuses %s %s", (method, path) => {
    expect(isAllowedRoute(method, path)).toBe(false);
  });
});

describe("validateRequest", () => {
  it("accepts a well-formed POST with a JSON body", () => {
    const request = validateRequest({ method: "POST", path: "/api/math/evaluate", body: { expression: "2+2" } });
    expect(request.body).toEqual({ expression: "2+2" });
  });

  it("rejects non-object payloads", () => {
    expect(() => validateRequest("GET /api/health")).toThrow(InvalidRequestError);
    expect(() => validateRequest(null)).toThrow(InvalidRequestError);
  });

  it("rejects a body on a GET request", () => {
    expect(() => validateRequest({ method: "GET", path: "/api/health", body: {} })).toThrow(/GET requests cannot/);
  });

  it("rejects oversized bodies", () => {
    const body = { expression: "x".repeat(20_000) };
    expect(() => validateRequest({ method: "POST", path: "/api/math/evaluate", body })).toThrow(/too large/);
  });

  it("rejects unknown methods and very long paths", () => {
    expect(() => validateRequest({ method: "PUT", path: "/api/health" })).toThrow(/Only GET and POST/);
    expect(() => validateRequest({ method: "GET", path: "/api/" + "a".repeat(600) })).toThrow(/too long/);
  });
});

describe("assistant route", () => {
  it("allows POST /api/assistant/ask and nothing else under it", async () => {
    const { isAllowedRoute, timeoutForPath, ASSISTANT_TIMEOUT_MS, DEFAULT_TIMEOUT_MS } = await import("../../src/shared/backendRoutes");
    expect(isAllowedRoute("POST", "/api/assistant/ask")).toBe(true);
    expect(isAllowedRoute("GET", "/api/assistant/ask")).toBe(false);
    expect(isAllowedRoute("POST", "/api/assistant/ask/../../health")).toBe(false);
    expect(isAllowedRoute("POST", "/api/assistant/anything-else")).toBe(false);
    expect(timeoutForPath("/api/assistant/ask")).toBe(ASSISTANT_TIMEOUT_MS);
    expect(timeoutForPath("/api/concepts?q=x")).toBe(DEFAULT_TIMEOUT_MS);
    expect(ASSISTANT_TIMEOUT_MS).toBeGreaterThan(120_000); // longer than the backend's default model timeout
  });
});
