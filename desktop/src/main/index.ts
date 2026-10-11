/**
 * Electron main process. Owns the window and the only path to the backend.
 *
 * Security settings (do not weaken them):
 *   contextIsolation: true   - the page cannot reach Electron internals
 *   nodeIntegration: false   - the page cannot use Node.js APIs
 *   sandbox: true            - the preload script runs in Chromium's sandbox
 */
import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "node:path";
import { type BackendRequest, type BackendResponse } from "../shared/backendRoutes";
import { forwardRequest, resolveBackendUrl } from "./backendProxy";

const IPC_CHANNEL = "mathengine:request";

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1180,
    height: 800,
    title: "MathEngine",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Never open new windows and never navigate away from the app itself.
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    void window.loadURL(devUrl);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  const backendUrl = resolveBackendUrl(process.env.MATHENGINE_BACKEND_URL);
  ipcMain.handle(IPC_CHANNEL, (_event, payload: unknown): Promise<BackendResponse> => {
    return forwardRequest(payload as BackendRequest, backendUrl);
  });
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
