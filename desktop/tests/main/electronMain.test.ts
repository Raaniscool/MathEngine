/**
 * Tests the REAL main-process wiring (src/main/index.ts) with a mocked "electron" module.
 *
 * The Electron binary cannot be downloaded in every environment, so these tests check the code that
 * configures Electron: window security options, navigation and popup policy, permission policy,
 * IPC sender checks, and startup failure handling. They do not start Electron itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => unknown;
  const state = {
    windows: [] as Array<{ options: Record<string, unknown>; handlers: Map<string, Handler>; loads: string[]; webContents: Record<string, unknown> }>,
    ipcHandlers: new Map<string, Handler>(),
    appHandlers: new Map<string, Handler>(),
    whenReady: (): Promise<void> => Promise.resolve(),
    quit: vi.fn(),
    errorBoxes: [] as Array<[string, string]>,
    permissionRequest: undefined as undefined | ((wc: unknown, perm: string, cb: (g: boolean) => void) => void),
    permissionCheck: undefined as undefined | ((wc: unknown, perm: string) => boolean),
  };
  class BrowserWindow {
    static getAllWindows() {
      return state.windows;
    }
    options: Record<string, unknown>;
    handlers = new Map<string, Handler>();
    loads: string[] = [];
    webContents: Record<string, unknown>;
    constructor(options: Record<string, unknown>) {
      this.options = options;
      const record = this;
      this.webContents = {
        setWindowOpenHandler: vi.fn(),
        on: (name: string, handler: Handler) => record.handlers.set(name, handler),
      };
      state.windows.push(this as never);
    }
    loadFile(path: string) {
      this.loads.push(`file:${path}`);
      return Promise.resolve();
    }
    loadURL(url: string) {
      this.loads.push(url);
      return Promise.resolve();
    }
  }
  const mod = {
    app: {
      whenReady: () => state.whenReady(),
      on: (name: string, handler: Handler) => state.appHandlers.set(name, handler),
      quit: state.quit,
      isReady: () => true,
    },
    BrowserWindow,
    ipcMain: { handle: (channel: string, handler: Handler) => state.ipcHandlers.set(channel, handler) },
    dialog: { showErrorBox: (title: string, body: string) => state.errorBoxes.push([title, body]) },
    session: {
      defaultSession: {
        setPermissionRequestHandler: (h: typeof state.permissionRequest) => (state.permissionRequest = h),
        setPermissionCheckHandler: (h: typeof state.permissionCheck) => (state.permissionCheck = h),
      },
    },
  };
  return { state, mod };
});

vi.mock("electron", () => electron.mod);

const { state } = electron;

async function startMain(env: Record<string, string | undefined> = {}) {
  vi.resetModules();
  state.windows.length = 0;
  state.ipcHandlers.clear();
  state.appHandlers.clear();
  state.errorBoxes.length = 0;
  state.quit.mockClear();
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  await import("../../src/main/index");
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function fakeFrame(url: string, isMain = true) {
  return { url, parent: isMain ? null : { url, parent: null } };
}

const originalFetch = globalThis.fetch;
const originalDevUrl = process.env.ELECTRON_RENDERER_URL;
const originalBackend = process.env.MATHENGINE_BACKEND_URL;

beforeEach(() => {
  delete process.env.ELECTRON_RENDERER_URL;
  delete process.env.MATHENGINE_BACKEND_URL;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalDevUrl === undefined) delete process.env.ELECTRON_RENDERER_URL;
  else process.env.ELECTRON_RENDERER_URL = originalDevUrl;
  if (originalBackend === undefined) delete process.env.MATHENGINE_BACKEND_URL;
  else process.env.MATHENGINE_BACKEND_URL = originalBackend;
  vi.restoreAllMocks();
});

describe("window security", () => {
  it("creates exactly one window with the hardened web preferences and the built preload", async () => {
    await startMain();
    expect(state.windows).toHaveLength(1);
    const { webPreferences, width, height } = state.windows[0].options as {
      webPreferences: Record<string, unknown>;
      width: number;
      height: number;
    };
    expect(webPreferences).toMatchObject({
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
    });
    expect(String(webPreferences.preload)).toMatch(/preload[\\/]index\.js$/);
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThan(0);
  });

  it("loads the packaged renderer from disk when no dev server is configured", async () => {
    await startMain();
    expect(state.windows[0].loads).toHaveLength(1);
    expect(state.windows[0].loads[0]).toMatch(/^file:.*renderer[\\/]index\.html$/);
  });

  it("loads the dev server URL instead when ELECTRON_RENDERER_URL is set", async () => {
    await startMain({ ELECTRON_RENDERER_URL: "http://localhost:5173/" });
    expect(state.windows[0].loads).toEqual(["http://localhost:5173/"]);
  });

  it("denies every window.open and popup request", async () => {
    await startMain();
    const setWindowOpenHandler = state.windows[0].webContents.setWindowOpenHandler as ReturnType<typeof vi.fn>;
    expect(setWindowOpenHandler).toHaveBeenCalledTimes(1);
    const handler = setWindowOpenHandler.mock.calls[0][0] as () => unknown;
    expect(handler()).toEqual({ action: "deny" });
  });

  it("prevents navigation and redirects away from the app page", async () => {
    await startMain();
    const navigate = state.windows[0].handlers.get("will-navigate") as (e: { preventDefault: () => void }, url: string) => void;
    const redirect = state.windows[0].handlers.get("will-redirect") as (e: { preventDefault: () => void }, url: string) => void;
    for (const handler of [navigate, redirect]) {
      const external = { preventDefault: vi.fn() };
      handler(external, "https://example.com/phish");
      expect(external.preventDefault).toHaveBeenCalled();
      const inApp = { preventDefault: vi.fn() };
      handler(inApp, state.windows[0].loads[0]);
      expect(inApp.preventDefault).not.toHaveBeenCalled();
    }
  });

  it("blocks webview attachment", async () => {
    await startMain();
    const attach = state.windows[0].handlers.get("will-attach-webview") as (e: { preventDefault: () => void }) => void;
    const event = { preventDefault: vi.fn() };
    attach(event);
    expect(event.preventDefault).toHaveBeenCalled();
  });
});

describe("permissions", () => {
  it("denies every browser permission request and check", async () => {
    await startMain();
    const callback = vi.fn();
    state.permissionRequest?.({}, "media", callback);
    expect(callback).toHaveBeenCalledWith(false);
    expect(state.permissionCheck?.({}, "geolocation")).toBe(false);
  });
});

describe("IPC from the renderer", () => {
  it("forwards a valid request from the app page to the backend", async () => {
    await startMain();
    const fetchMock = vi.fn(async () => new Response('{"status":"ok"}', { status: 200 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const handler = state.ipcHandlers.get("mathengine:request") as (e: unknown, p: unknown) => Promise<unknown>;
    const result = await handler({ senderFrame: fakeFrame(state.windows[0].loads[0]) }, { method: "GET", path: "/api/health" });
    expect(result).toMatchObject({ ok: true, status: 200, data: { status: "ok" } });
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/health", expect.anything());
  });

  it("refuses requests from a foreign page and never calls the backend", async () => {
    await startMain();
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const handler = state.ipcHandlers.get("mathengine:request") as (e: unknown, p: unknown) => unknown;
    const result = await handler({ senderFrame: fakeFrame("https://evil.example/") }, { method: "GET", path: "/api/health" });
    expect(result).toMatchObject({ ok: false, status: 0 });
    expect(String((result as { error: string }).error)).toMatch(/did not come from the MathEngine window/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses requests from an iframe, even one that shows the app page", async () => {
    await startMain();
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const handler = state.ipcHandlers.get("mathengine:request") as (e: unknown, p: unknown) => unknown;
    const result = await handler({ senderFrame: fakeFrame(state.windows[0].loads[0], false) }, { method: "GET", path: "/api/health" });
    expect(result).toMatchObject({ ok: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses requests with no sender frame", async () => {
    await startMain();
    const handler = state.ipcHandlers.get("mathengine:request") as (e: unknown, p: unknown) => unknown;
    expect(await handler({ senderFrame: null }, { method: "GET", path: "/api/health" })).toMatchObject({ ok: false });
  });

  it("rejects a route the allowlist does not contain, even from the app page", async () => {
    await startMain();
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const handler = state.ipcHandlers.get("mathengine:request") as (e: unknown, p: unknown) => Promise<unknown>;
    const result = await handler(
      { senderFrame: fakeFrame(state.windows[0].loads[0]) },
      { method: "POST", path: "/api/actions/run_shell", body: {} },
    );
    expect(result).toMatchObject({ ok: false, status: 400 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not open a second window when activate fires while a window is already open", async () => {
    await startMain();
    const activate = state.appHandlers.get("activate") as () => void;
    activate();
    expect(state.windows).toHaveLength(1);
  });

  it("registers the IPC handler once, even when the window is re-created on activate", async () => {
    await startMain();
    expect(state.ipcHandlers.size).toBe(1);
    const activate = state.appHandlers.get("activate") as () => void;
    state.windows.length = 0;
    activate();
    expect(state.windows).toHaveLength(1);
    expect(state.ipcHandlers.size).toBe(1);
  });
});

describe("startup failures", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("shows an error and quits when MATHENGINE_BACKEND_URL is not loopback http", async () => {
    await startMain({ MATHENGINE_BACKEND_URL: "https://example.com" });
    expect(state.windows).toHaveLength(0);
    expect(state.errorBoxes).toHaveLength(1);
    expect(state.errorBoxes[0][0]).toBe("MathEngine cannot start");
    expect(state.errorBoxes[0][1]).toMatch(/127\.0\.0\.1 or localhost/);
    expect(state.quit).toHaveBeenCalled();
  });

  it("shows an error and quits when MATHENGINE_BACKEND_URL is not a URL", async () => {
    await startMain({ MATHENGINE_BACKEND_URL: "not a url" });
    expect(state.errorBoxes[0][1]).toMatch(/not a valid URL/);
    expect(state.quit).toHaveBeenCalled();
  });

  it("shows an error and quits when Electron fails to become ready", async () => {
    state.whenReady = () => Promise.reject(new Error("GPU process crashed"));
    try {
      await startMain();
    } finally {
      state.whenReady = () => Promise.resolve();
    }
    expect(state.errorBoxes[0][1]).toBe("GPU process crashed");
    expect(state.quit).toHaveBeenCalled();
  });

  it("uses the default backend address when MATHENGINE_BACKEND_URL is unset", async () => {
    await startMain();
    expect(state.errorBoxes).toHaveLength(0);
    expect(state.quit).not.toHaveBeenCalled();
  });
});
