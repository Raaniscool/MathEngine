/**
 * Security decisions for the Electron main process, kept free of Electron imports so they can be
 * unit-tested directly. index.ts applies them to the real BrowserWindow, session, and IPC handlers.
 */
import { pathToFileURL } from "node:url";

/** Web preferences for the app window. Do not weaken any of these without a documented reason. */
export const SECURE_WEB_PREFERENCES = {
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
  webviewTag: false,
} as const;

export interface AppUrls {
  /** The packaged renderer page, e.g. file:///.../out/renderer/index.html */
  indexFileUrl: string;
  /** The dev server origin when running `electron-vite dev`, otherwise undefined. */
  devOrigin?: string;
}

export function appUrlsFor(indexHtmlPath: string, devUrl: string | undefined): AppUrls {
  const urls: AppUrls = { indexFileUrl: pathToFileURL(indexHtmlPath).href };
  if (devUrl) {
    urls.devOrigin = new URL(devUrl).origin;
  }
  return urls;
}

/** True only for the app's own page. Remote pages, other files, and other origins are not the app. */
export function isAppUrl(url: string, urls: AppUrls): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol === "file:") {
    return new URL(urls.indexFileUrl).pathname === parsed.pathname;
  }
  return urls.devOrigin !== undefined && parsed.origin === urls.devOrigin;
}

/** Minimal view of an Electron WebFrameMain, enough to check who sent an IPC message. */
export interface FrameLike {
  url: string;
  parent: FrameLike | null;
}

/** Accept IPC only from the app's own top-level page. Sub-frames and foreign pages are refused. */
export function isTrustedSender(frame: FrameLike | null | undefined, urls: AppUrls): boolean {
  return frame !== null && frame !== undefined && frame.parent === null && isAppUrl(frame.url, urls);
}

export const REFUSED_SENDER_MESSAGE = "Request refused: it did not come from the MathEngine window.";

/** Deny every browser permission (camera, microphone, geolocation, notifications, and so on). */
export interface PermissionSession {
  setPermissionRequestHandler(handler: (webContents: unknown, permission: string, callback: (granted: boolean) => void) => void): void;
  setPermissionCheckHandler(handler: (webContents: unknown, permission: string) => boolean): void;
}

export function denyAllPermissions(session: PermissionSession): void {
  session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  session.setPermissionCheckHandler(() => false);
}
