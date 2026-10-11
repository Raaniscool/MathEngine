import { afterEach, describe, expect, it } from "vitest";
import { ApiError, api, buildQuery, describeFailure } from "../../src/renderer/src/api";
import { describeVerdict } from "../../src/renderer/src/verdict";
import type { CheckResponse } from "../../src/shared/apiTypes";

type Request = { method: string; path: string; body?: unknown };

function installBridge(respond: (request: Request) => unknown): Request[] {
  const seen: Request[] = [];
  (globalThis as unknown as { window: unknown }).window = {
    mathengine: {
      request: async (request: Request) => {
        seen.push(request);
        return respond(request) as never;
      },
    },
  };
  return seen;
}

afterEach(() => {
  delete (globalThis as unknown as { window?: unknown }).window;
});

describe("buildQuery", () => {
  it("skips empty values and encodes the rest", () => {
    expect(buildQuery({ q: "power rule", subject: undefined, include_drafts: false, limit: 5 })).toBe("?q=power+rule&limit=5");
    expect(buildQuery({ q: "", subject: null })).toBe("");
  });
});

describe("describeFailure", () => {
  it("prefers the transport error, then FastAPI's detail, then the status", () => {
    expect(describeFailure({ ok: false, status: 0, data: null, error: "backend down" })).toBe("backend down");
    expect(describeFailure({ ok: false, status: 404, data: { detail: "No concept" } })).toBe("No concept");
    expect(describeFailure({ ok: false, status: 500, data: null })).toBe("The backend returned HTTP 500.");
  });
});

describe("api client", () => {
  it("sends every call through the preload bridge with the right route", async () => {
    const seen = installBridge(() => ({ ok: true, status: 200, data: { subjects: [] } }));
    await api.subjects(false);
    await api.concept("arithmetic.multiplication.facts", true);
    expect(seen.map((item) => item.path)).toEqual([
      "/api/subjects",
      "/api/concepts/arithmetic.multiplication.facts?include_drafts=true",
    ]);
  });

  it("sends the check request body without any answer key", async () => {
    const seen = installBridge(() => ({ ok: true, status: 200, data: {} }));
    await api.checkAnswer("arithmetic.multiplication.facts", "seven-times-eight", "56", false);
    expect(seen[0]).toEqual({
      method: "POST",
      path: "/api/exercises/check",
      body: { concept_id: "arithmetic.multiplication.facts", exercise_id: "seven-times-eight", answer: "56", include_drafts: false },
    });
  });

  it("throws ApiError with a readable message on failure", async () => {
    installBridge(() => ({ ok: false, status: 404, data: { detail: "No concept with id 'x'." } }));
    await expect(api.concept("arithmetic.x.y", false)).rejects.toBeInstanceOf(ApiError);
    await expect(api.concept("arithmetic.x.y", false)).rejects.toThrow("No concept with id 'x'.");
  });
});

describe("verdict wording", () => {
  const base: CheckResponse = { verdict: "correct", verified: true, method: "exact_numeric", message: "", feedback: "", attempt_id: 1 };

  it("only says 'checked by the math engine' when a check really ran", () => {
    expect(describeVerdict({ ...base, verdict: "incorrect" }).provenance).toBe("Checked by the math engine.");
    expect(describeVerdict({ ...base, verdict: "unverifiable", verified: false }).headline).toBe("No verdict given");
    expect(describeVerdict({ ...base, verdict: "unverifiable", verified: false }).provenance).toMatch(/not marked right or wrong/);
  });
});
