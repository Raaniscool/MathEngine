import { describe, expect, it } from "vitest";
import { DEFAULT_BACKEND_URL, forwardRequest, resolveBackendUrl, type FetchLike } from "../../src/main/backendProxy";

const BASE = "http://127.0.0.1:8000";

function fakeFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>): FetchLike {
  return async (url, init) => handler(url, init);
}

describe("resolveBackendUrl", () => {
  it("defaults to the local backend", () => {
    expect(resolveBackendUrl(undefined)).toBe(DEFAULT_BACKEND_URL);
    expect(resolveBackendUrl("   ")).toBe(DEFAULT_BACKEND_URL);
  });

  it("accepts loopback http addresses", () => {
    expect(resolveBackendUrl("http://localhost:9000/")).toBe("http://localhost:9000");
  });

  it("refuses remote hosts and https so the engine cannot be pointed at another server", () => {
    expect(() => resolveBackendUrl("http://example.com:8000")).toThrow(/127.0.0.1 or localhost/);
    expect(() => resolveBackendUrl("https://127.0.0.1:8000")).toThrow(/http:\/\//);
    expect(() => resolveBackendUrl("not a url")).toThrow(/not a valid URL/);
  });
});

describe("forwardRequest", () => {
  it("forwards an allowed GET and returns parsed JSON", async () => {
    const seen: string[] = [];
    const result = await forwardRequest(
      { method: "GET", path: "/api/health" },
      BASE,
      fakeFetch((url) => {
        seen.push(url);
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }),
    );
    expect(seen).toEqual([`${BASE}/api/health`]);
    expect(result).toEqual({ ok: true, status: 200, data: { status: "ok" } });
  });

  it("sends JSON bodies for allowed POST routes", async () => {
    let sent: unknown = null;
    await forwardRequest(
      { method: "POST", path: "/api/math/evaluate", body: { expression: "3*4" } },
      BASE,
      fakeFetch((_url, init) => {
        sent = JSON.parse(String(init.body));
        return new Response("{}", { status: 200 });
      }),
    );
    expect(sent).toEqual({ expression: "3*4" });
  });

  it("never forwards disallowed routes", async () => {
    let called = false;
    const result = await forwardRequest(
      { method: "POST", path: "/api/knowledge/reload" },
      BASE,
      fakeFetch(() => {
        called = true;
        return new Response("{}");
      }),
    );
    expect(called).toBe(false);
    expect(result.ok).toBe(false);
    expect(result.status).toBe(400);
  });

  it("passes backend error responses through with their status", async () => {
    const result = await forwardRequest(
      { method: "POST", path: "/api/math/evaluate", body: { expression: "1/0" } },
      BASE,
      fakeFetch(() => new Response(JSON.stringify({ detail: "division by zero" }), { status: 422 })),
    );
    expect(result).toEqual({ ok: false, status: 422, data: { detail: "division by zero" } });
  });

  it("explains clearly when the backend is not running", async () => {
    const result = await forwardRequest(
      { method: "GET", path: "/api/health" },
      BASE,
      fakeFetch(() => {
        throw new TypeError("fetch failed");
      }),
    );
    expect(result.status).toBe(0);
    expect(result.error).toMatch(/not reachable at http:\/\/127\.0\.0\.1:8000/);
  });
});
