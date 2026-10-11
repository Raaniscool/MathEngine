/**
 * Preload script: the ONLY bridge between the web page and Electron.
 *
 * It exposes exactly one function, window.mathengine.request, and nothing else. It does not expose
 * ipcRenderer, Node.js, or the file system. The main process validates every call.
 */
import { contextBridge, ipcRenderer } from "electron";
import { IPC_CHANNEL } from "../shared/ipc";

export interface MathEngineBridgeRequest {
  method: string;
  path: string;
  body?: unknown;
}

const bridge = {
  request: (request: MathEngineBridgeRequest) => ipcRenderer.invoke(IPC_CHANNEL, request),
};

contextBridge.exposeInMainWorld("mathengine", bridge);
