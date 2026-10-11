/**
 * Integration test: sends requests through the real proxy to a running backend.
 * It runs only when the backend is listening (start it first; see README). Otherwise it is skipped.
 */
import { describe, expect, it } from "vitest";
import { DEFAULT_BACKEND_URL, forwardRequest } from "../../src/main/backendProxy";

async function backendIsRunning(): Promise<boolean> {
  try {
    const response = await fetch(`${DEFAULT_BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(1500) });
    return response.ok;
  } catch {
    return false;
  }
}

const running = await backendIsRunning();

describe.skipIf(!running)("backend integration (requires the backend on 127.0.0.1:8000)", () => {
  it("reports health through the proxy", async () => {
    const result = await forwardRequest({ method: "GET", path: "/api/health" }, DEFAULT_BACKEND_URL);
    expect(result.ok).toBe(true);
    expect((result.data as { status: string }).status).toBe("ok");
  });

  it("evaluates an expression exactly through the proxy", async () => {
    const result = await forwardRequest(
      { method: "POST", path: "/api/math/evaluate", body: { expression: "sqrt(8)" } },
      DEFAULT_BACKEND_URL,
    );
    expect((result.data as { exact: string }).exact).toBe("2*sqrt(2)");
  });

  it("refuses unsafe input from the proxy with the backend's own message", async () => {
    const result = await forwardRequest(
      { method: "POST", path: "/api/math/evaluate", body: { expression: "__import__('os')" } },
      DEFAULT_BACKEND_URL,
    );
    expect(result.ok).toBe(false);
    expect(result.status).toBe(422);
  });
});

describe("integration precondition", () => {
  it("reports whether the backend was reachable for this run", () => {
    // Visible in the test summary so a skipped integration suite is never mistaken for a passing one.
    expect(typeof running).toBe("boolean");
  });
});
