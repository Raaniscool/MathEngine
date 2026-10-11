// Browser preview of the MathEngine UI, for development only.
//
// The real app is the Electron window. In Electron, the preload script provides window.mathengine.
// This server serves the same built renderer in an ordinary browser and provides a stand-in for that
// bridge, so the UI can be looked at without Electron. It is not used in the packaged app.
//
// Usage (after `npm run build`):   npm run preview:browser
// Then open http://127.0.0.1:5173/ in your browser. The backend must be running (README step 4).
//
// Environment variables:
//   MATHENGINE_PREVIEW_HOST  address to listen on   (default 127.0.0.1; use 0.0.0.0 to share on your network)
//   MATHENGINE_PREVIEW_PORT  port                   (default 5173)
//   MATHENGINE_BACKEND_URL   backend address        (default http://127.0.0.1:8000; loopback only)
//
// Differences from the Electron app, all deliberate and limited to this preview:
//   - The production Content-Security-Policy blocks fetch(). This server relaxes connect-src to 'self' in the
//     HTML it serves, so the page can call its own /api path. The built files on disk are not changed.
//   - The bridge calls /api directly, instead of going through the Electron main-process allowlist. The
//     backend still validates every request, and this server forwards only /api paths.

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_RENDERER_DIR = path.resolve(SCRIPT_DIR, "..", "out", "renderer");
export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const SHIM_PATH = "/__preview/shim.js";

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".map": "application/json",
  ".json": "application/json",
};

// Same contract as the preload bridge: request({ method, path, body }) -> { ok, status, data, error? }.
export const BRIDGE_SHIM = `
window.mathengine = {
  request: async ({ method, path, body }) => {
    if (typeof path !== "string" || !path.startsWith("/api/")) {
      return { ok: false, status: 400, data: null, error: "Only /api routes are allowed in the browser preview." };
    }
    if (method !== "GET" && method !== "POST") {
      return { ok: false, status: 400, data: null, error: "Only GET and POST are allowed." };
    }
    try {
      const init = { method, headers: { Accept: "application/json" } };
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      const response = await fetch(path, init);
      const text = await response.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      return { ok: response.ok, status: response.status, data };
    } catch {
      return { ok: false, status: 0, data: null, error: "The MathEngine backend is not reachable. Start it first (README step 4)." };
    }
  },
};
`;

/** Returns the index.html the browser preview serves: relaxed connect-src, and the bridge loaded first. */
export function previewIndexHtml(originalHtml) {
  if (!originalHtml.includes("connect-src 'none'")) {
    throw new Error("Expected the production CSP (connect-src 'none') in index.html. Run `npm run build` first.");
  }
  if (!originalHtml.includes('<script type="module"')) {
    throw new Error("Expected the app bundle script tag in index.html. Run `npm run build` first.");
  }
  return originalHtml
    .replace("connect-src 'none'", "connect-src 'self'")
    .replace('<script type="module"', `<script src="${SHIM_PATH}"></script>\n    <script type="module"`);
}

/** Resolves a request path to a file inside rendererDir, or null if it is outside it or missing. */
export function resolveRendererFile(rendererDir, urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  const root = path.resolve(rendererDir);
  const candidate = path.resolve(root, decoded === "/" ? "index.html" : `.${decoded}`);
  if (candidate !== root && !candidate.startsWith(root + path.sep)) return null;
  if (!fs.existsSync(candidate) || fs.statSync(candidate).isDirectory()) return null;
  return candidate;
}

function forwardToBackend(req, res, backendUrl) {
  const target = new URL(req.url, backendUrl);
  const upstream = http.request(
    {
      hostname: target.hostname,
      port: target.port,
      path: target.pathname + target.search,
      method: req.method,
      headers: { "content-type": req.headers["content-type"] ?? "application/json", accept: "application/json" },
      // The assistant waits on a local model, so it gets the same longer limit as the Electron proxy.
      timeout: target.pathname === "/api/assistant/ask" ? 150000 : 10000,
    },
    (up) => {
      res.writeHead(up.statusCode ?? 502, { "content-type": up.headers["content-type"] ?? "application/json" });
      up.pipe(res);
    },
  );
  upstream.on("timeout", () => upstream.destroy(new Error("timeout")));
  upstream.on("error", () => {
    if (res.headersSent) return res.end();
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "The MathEngine backend is not reachable. Start it first (README step 4)." }));
  });
  req.pipe(upstream);
}

/** Creates the preview server. Exported so the tests can run it on a free port. */
export function createPreviewServer({ rendererDir = DEFAULT_RENDERER_DIR, backendUrl = DEFAULT_BACKEND_URL } = {}) {
  const backend = new URL(backendUrl);
  const loopback = backend.hostname === "127.0.0.1" || backend.hostname === "localhost";
  if (backend.protocol !== "http:" || !loopback) {
    throw new Error("MATHENGINE_BACKEND_URL must be an http:// address on 127.0.0.1 or localhost.");
  }

  return http.createServer((req, res) => {
    const urlPath = (req.url ?? "/").split("?")[0];
    if (urlPath.startsWith("/api/")) return forwardToBackend(req, res, backend.origin);
    if (urlPath === SHIM_PATH) {
      res.writeHead(200, { "content-type": CONTENT_TYPES[".js"] });
      return res.end(BRIDGE_SHIM);
    }
    const file = resolveRendererFile(rendererDir, urlPath);
    if (!file) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      return res.end("Not found");
    }
    if (file.endsWith("index.html")) {
      res.writeHead(200, { "content-type": CONTENT_TYPES[".html"] });
      return res.end(previewIndexHtml(fs.readFileSync(file, "utf8")));
    }
    res.writeHead(200, { "content-type": CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
}

function main() {
  const host = process.env.MATHENGINE_PREVIEW_HOST || "127.0.0.1";
  const port = Number(process.env.MATHENGINE_PREVIEW_PORT || 5173);
  const backendUrl = process.env.MATHENGINE_BACKEND_URL || DEFAULT_BACKEND_URL;
  if (!fs.existsSync(path.join(DEFAULT_RENDERER_DIR, "index.html"))) {
    console.error("The built UI was not found. Run `npm run build` first.");
    process.exit(1);
  }
  const server = createPreviewServer({ backendUrl });
  server.listen(port, host, () => {
    console.log(`MathEngine browser preview: http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${port}/`);
    console.log(`Backend: ${backendUrl}`);
    console.log("Press Ctrl+C to stop.");
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main();
}
