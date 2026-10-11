/** Tests for the development browser preview (scripts/browser-preview.mjs). Uses a fake backend. */
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  BRIDGE_SHIM,
  createPreviewServer,
  previewIndexHtml,
  resolveRendererFile,
  SHIM_PATH,
} from "../../scripts/browser-preview.mjs";

const PRODUCTION_HTML = `<!doctype html>
<html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; connect-src 'none'; object-src 'none'" />
<script type="module" crossorigin src="./assets/index-test.js"></script>
</head><body><div id="root"></div></body></html>`;

let root;
let rendererDir;
let backend;
let backendPort;
let preview;
let previewPort;
const seen = [];

function get(port, urlPath, options = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: "127.0.0.1", port, path: urlPath, method: options.method ?? "GET", headers: options.headers ?? {} }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on("error", reject);
    if (options.body !== undefined) req.write(options.body);
    req.end();
  });
}

beforeAll(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "mathengine-preview-"));
  rendererDir = path.join(root, "renderer");
  fs.mkdirSync(path.join(rendererDir, "assets"), { recursive: true });
  fs.writeFileSync(path.join(rendererDir, "index.html"), PRODUCTION_HTML);
  fs.writeFileSync(path.join(rendererDir, "assets", "index-test.js"), "console.log('app');");
  fs.writeFileSync(path.join(root, "secret.txt"), "do not serve");

  backend = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      seen.push({ method: req.method, url: req.url, body });
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ echoed: req.url, method: req.method }));
    });
  });
  await new Promise((resolve) => backend.listen(0, "127.0.0.1", resolve));
  backendPort = backend.address().port;

  preview = createPreviewServer({ rendererDir, backendUrl: `http://127.0.0.1:${backendPort}` });
  await new Promise((resolve) => preview.listen(0, "127.0.0.1", resolve));
  previewPort = preview.address().port;
});

afterAll(async () => {
  await new Promise((resolve) => preview.close(resolve));
  await new Promise((resolve) => backend.close(resolve));
  fs.rmSync(root, { recursive: true, force: true });
});

describe("previewIndexHtml", () => {
  it("relaxes connect-src to 'self' and loads the bridge before the app bundle", () => {
    const html = previewIndexHtml(PRODUCTION_HTML);
    expect(html).toContain("connect-src 'self'");
    expect(html).not.toContain("connect-src 'none'");
    expect(html.indexOf(SHIM_PATH)).toBeLessThan(html.indexOf('type="module"'));
  });

  it("refuses HTML that is not the production build", () => {
    expect(() => previewIndexHtml("<html></html>")).toThrow(/npm run build/);
  });

  it("leaves the other CSP directives unchanged", () => {
    expect(previewIndexHtml(PRODUCTION_HTML)).toContain("script-src 'self'; connect-src 'self'; object-src 'none'");
  });
});

describe("resolveRendererFile", () => {
  it("resolves files inside the renderer folder", () => {
    expect(resolveRendererFile(rendererDir, "/")).toBe(path.join(rendererDir, "index.html"));
    expect(resolveRendererFile(rendererDir, "/assets/index-test.js")).toBe(path.join(rendererDir, "assets", "index-test.js"));
  });

  it("refuses paths that escape the renderer folder", () => {
    expect(resolveRendererFile(rendererDir, "/../secret.txt")).toBeNull();
    expect(resolveRendererFile(rendererDir, "/%2e%2e/secret.txt")).toBeNull();
    expect(resolveRendererFile(rendererDir, "/..%2fsecret.txt")).toBeNull();
    expect(resolveRendererFile(rendererDir, "/%E0%A4%A")).toBeNull();
  });

  it("returns null for missing files and folders", () => {
    expect(resolveRendererFile(rendererDir, "/nope.js")).toBeNull();
    expect(resolveRendererFile(rendererDir, "/assets")).toBeNull();
  });
});

describe("browser preview server", () => {
  it("serves the page with the bridge and the relaxed CSP", async () => {
    const response = await get(previewPort, "/");
    expect(response.status).toBe(200);
    expect(response.headers["content-type"]).toMatch(/text\/html/);
    expect(response.body).toContain(SHIM_PATH);
    expect(response.body).toContain("connect-src 'self'");
  });

  it("serves the bridge script", async () => {
    const response = await get(previewPort, SHIM_PATH);
    expect(response.status).toBe(200);
    expect(response.body).toBe(BRIDGE_SHIM);
    expect(response.body).toContain("window.mathengine");
  });

  it("forwards GET /api requests to the backend", async () => {
    const response = await get(previewPort, "/api/concepts?q=times+tables");
    expect(response.status).toBe(200);
    expect(JSON.parse(response.body)).toEqual({ echoed: "/api/concepts?q=times+tables", method: "GET" });
  });

  it("forwards POST /api bodies to the backend", async () => {
    const body = JSON.stringify({ expression: "6*7" });
    const response = await get(previewPort, "/api/math/evaluate", {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) },
      body,
    });
    expect(response.status).toBe(200);
    const last = seen[seen.length - 1];
    expect(last.method).toBe("POST");
    expect(last.body).toBe(body);
  });

  it("does not forward non-/api paths to the backend", async () => {
    const response = await get(previewPort, "/../secret.txt");
    expect(response.status).toBe(404);
    expect(response.body).not.toContain("do not serve");
  });

  it("returns 404 for a missing asset", async () => {
    expect((await get(previewPort, "/assets/missing.js")).status).toBe(404);
  });

  it("serves an asset with its content type", async () => {
    const response = await get(previewPort, "/assets/index-test.js");
    expect(response.status).toBe(200);
    expect(response.headers["content-type"]).toMatch(/javascript/);
  });

  it("returns a readable error when the backend is down", async () => {
    const down = createPreviewServer({ rendererDir, backendUrl: "http://127.0.0.1:1" });
    await new Promise((resolve) => down.listen(0, "127.0.0.1", resolve));
    try {
      const response = await get(down.address().port, "/api/health");
      expect(response.status).toBe(502);
      expect(response.body).toMatch(/not reachable/);
    } finally {
      await new Promise((resolve) => down.close(resolve));
    }
  });

  it("refuses a backend address that is not loopback", () => {
    expect(() => createPreviewServer({ rendererDir, backendUrl: "https://example.com" })).toThrow(/127\.0\.0\.1 or localhost/);
  });
});
