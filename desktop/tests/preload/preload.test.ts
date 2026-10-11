/** Tests the REAL preload script with a mocked "electron" module. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => ({
  exposed: new Map<string, unknown>(),
  invoke: vi.fn(async (..._args: unknown[]) => ({ ok: true, status: 200, data: { hello: true } })),
}));

vi.mock("electron", () => ({
  contextBridge: {
    exposeInMainWorld: (key: string, api: unknown) => electron.exposed.set(key, api),
  },
  ipcRenderer: { invoke: electron.invoke },
}));

beforeEach(async () => {
  vi.resetModules();
  electron.exposed.clear();
  electron.invoke.mockClear();
  await import("../../src/preload/index");
});

describe("preload bridge", () => {
  it("exposes exactly one object, window.mathengine, with exactly one function: request", () => {
    expect([...electron.exposed.keys()]).toEqual(["mathengine"]);
    const api = electron.exposed.get("mathengine") as Record<string, unknown>;
    expect(Object.keys(api)).toEqual(["request"]);
    expect(typeof api.request).toBe("function");
  });

  it("uses only the single allowed channel, so nothing else reaches the main process", async () => {
    const api = electron.exposed.get("mathengine") as { request: (r: unknown) => Promise<unknown> };
    await api.request({ method: "POST", path: "/api/math/evaluate", body: { expression: "1+1" } });
    const channels = electron.invoke.mock.calls.map((call) => call[0]);
    expect(channels).toEqual(["mathengine:request"]);
  });

  it("sends each request to the main process on the single allowed channel", async () => {
    const api = electron.exposed.get("mathengine") as { request: (r: unknown) => Promise<unknown> };
    const request = { method: "GET", path: "/api/health" };
    const result = await api.request(request);
    expect(electron.invoke).toHaveBeenCalledWith("mathengine:request", request);
    expect(result).toEqual({ ok: true, status: 200, data: { hello: true } });
  });
});
