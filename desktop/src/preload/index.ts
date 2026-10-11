/**
 * Preload script: the ONLY bridge between the web page and Electron.
 *
 * It exposes a single function, window.mathengine.request. The main process validates every call,
 * so this bridge does not need to be trusted to enforce the allowlist.
 */
import { contextBridge, ipcRenderer } from "electron";

const IPC_CHANNEL = "mathengine:request";

contextBridge.exposeInMainWorld("mathengine", {
  request: (request: { method: string; path: string; body?: unknown }) => ipcRenderer.invoke(IPC_CHANNEL, request),
});
