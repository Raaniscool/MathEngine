/** Unit tests for the Electron security policy helpers (src/main/security.ts). No Electron needed. */
import { describe, expect, it, vi } from "vitest";
import {
  appUrlsFor,
  denyAllPermissions,
  isAppUrl,
  isTrustedSender,
  SECURE_WEB_PREFERENCES,
} from "../../src/main/security";

const urls = appUrlsFor("/app/out/renderer/index.html", undefined);
const devUrls = appUrlsFor("/app/out/renderer/index.html", "http://localhost:5173/");

describe("SECURE_WEB_PREFERENCES", () => {
  it("keeps the settings the architecture depends on", () => {
    expect(SECURE_WEB_PREFERENCES.contextIsolation).toBe(true);
    expect(SECURE_WEB_PREFERENCES.nodeIntegration).toBe(false);
    expect(SECURE_WEB_PREFERENCES.sandbox).toBe(true);
    expect(SECURE_WEB_PREFERENCES.webSecurity).toBe(true);
  });
});

describe("isAppUrl", () => {
  it("accepts the packaged index page, with or without a hash or query", () => {
    expect(isAppUrl(urls.indexFileUrl, urls)).toBe(true);
    expect(isAppUrl(`${urls.indexFileUrl}#/x`, urls)).toBe(true);
    expect(isAppUrl(`${urls.indexFileUrl}?a=1`, urls)).toBe(true);
  });

  it("rejects other files, other paths, and remote URLs", () => {
    expect(isAppUrl("file:///etc/passwd", urls)).toBe(false);
    expect(isAppUrl("file:///app/out/renderer/other.html", urls)).toBe(false);
    expect(isAppUrl("https://example.com/", urls)).toBe(false);
    expect(isAppUrl("javascript:alert(1)", urls)).toBe(false);
    expect(isAppUrl("not a url", urls)).toBe(false);
  });

  it("accepts only the dev origin in development, never other localhost ports", () => {
    expect(isAppUrl("http://localhost:5173/", devUrls)).toBe(true);
    expect(isAppUrl("http://localhost:5173/anything", devUrls)).toBe(true);
    expect(isAppUrl("http://localhost:9999/", devUrls)).toBe(false);
    expect(isAppUrl("http://127.0.0.1:5173/", devUrls)).toBe(false);
  });

  it("does not accept the dev origin when not in development", () => {
    expect(isAppUrl("http://localhost:5173/", urls)).toBe(false);
  });
});

describe("isTrustedSender", () => {
  it("trusts only the top-level app page", () => {
    expect(isTrustedSender({ url: urls.indexFileUrl, parent: null }, urls)).toBe(true);
  });

  it("refuses sub-frames, foreign pages, and missing frames", () => {
    expect(isTrustedSender({ url: urls.indexFileUrl, parent: { url: urls.indexFileUrl, parent: null } }, urls)).toBe(false);
    expect(isTrustedSender({ url: "https://evil.example/", parent: null }, urls)).toBe(false);
    expect(isTrustedSender(null, urls)).toBe(false);
    expect(isTrustedSender(undefined, urls)).toBe(false);
  });
});

describe("denyAllPermissions", () => {
  it("answers every request with false and every check with false", () => {
    const session = {
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
    };
    denyAllPermissions(session);
    const requestHandler = session.setPermissionRequestHandler.mock.calls[0][0] as (
      wc: unknown,
      perm: string,
      cb: (g: boolean) => void,
    ) => void;
    const callback = vi.fn();
    requestHandler({}, "notifications", callback);
    expect(callback).toHaveBeenCalledWith(false);
    const checkHandler = session.setPermissionCheckHandler.mock.calls[0][0] as () => boolean;
    expect(checkHandler()).toBe(false);
  });
});
