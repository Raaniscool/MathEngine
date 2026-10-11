/**
 * Electron main process. Owns the window and the only path from the page to the backend.
 *
 * Security settings are defined in ./security.ts and applied here. Do not weaken them:
 *   contextIsolation: true   - the page cannot reach Electron internals
 *   nodeIntegration: false   - the page cannot use Node.js APIs
 *   sandbox: true            - the preload script runs in Chromium's sandbox
 * Every IPC request is checked for its sender and its route before it reaches the backend.
 */
import { app, BrowserWindow, dialog, ipcMain, session } from "electron";
import { join } from "node:path";
import { type BackendRequest, type BackendResponse } from "../shared/backendRoutes";
import { IPC_CHANNEL } from "../shared/ipc";
import { forwardRequest, resolveBackendUrl } from "./backendProxy";
import {
  appUrlsFor,
  type AppUrls,
  denyAllPermissions,
  isAppUrl,
  isTrustedSender,
  REFUSED_SENDER_MESSAGE,
  SECURE_WEB_PREFERENCES,
} from "./security";

function createWindow(urls: AppUrls, devUrl: string | undefined): void {
  const window = new BrowserWindow({
    width: 1180,
    height: 800,
    title: "MathEngine",
    webPreferences: {
      ...SECURE_WEB_PREFERENCES,
      preload: join(__dirname, "../preload/index.js"),
    },
  });

  const web = window.webContents;
  // Never open new windows, never attach webviews, and never leave the app's own page.
  web.setWindowOpenHandler(() => ({ action: "deny" }));
  web.on("will-attach-webview", (event) => event.preventDefault());
  const keepInApp = (event: { preventDefault(): void }, url: string) => {
    if (!isAppUrl(url, urls)) event.preventDefault();
  };
  web.on("will-navigate", keepInApp);
  web.on("will-redirect", keepInApp);

  if (devUrl) {
    void window.loadURL(devUrl);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

// Set once at startup. Re-creating the window (macOS "activate") reuses them, and never re-registers IPC.
let appUrls: AppUrls | undefined;
let devUrl: string | undefined;

function startupFailed(message: string): void {
  console.error(`MathEngine failed to start: ${message}`);
  dialog.showErrorBox("MathEngine cannot start", message);
  app.quit();
}

function start(): void {
  let backendUrl: string;
  try {
    backendUrl = resolveBackendUrl(process.env.MATHENGINE_BACKEND_URL);
  } catch (error) {
    startupFailed((error as Error).message);
    return;
  }

  devUrl = process.env.ELECTRON_RENDERER_URL || undefined;
  appUrls = appUrlsFor(join(__dirname, "../renderer/index.html"), devUrl);
  const trustedUrls = appUrls;

  denyAllPermissions(session.defaultSession);
  ipcMain.handle(IPC_CHANNEL, (event, payload: unknown): Promise<BackendResponse> | BackendResponse => {
    if (!isTrustedSender(event.senderFrame, trustedUrls)) {
      return { ok: false, status: 0, data: null, error: REFUSED_SENDER_MESSAGE };
    }
    return forwardRequest(payload as BackendRequest, backendUrl);
  });
  createWindow(trustedUrls, devUrl);
}

app
  .whenReady()
  .then(start)
  .catch((error: unknown) => startupFailed(error instanceof Error ? error.message : String(error)));

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && appUrls) createWindow(appUrls, devUrl);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
