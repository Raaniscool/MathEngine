import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import type { Plugin } from "vite";

// Content-Security-Policy for the built renderer. Development skips it, because React Fast Refresh
// needs inline scripts that the policy would block. The production build always gets the policy.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'none'", // the page must use the preload bridge, never fetch() directly
  "object-src 'none'",
  "base-uri 'none'",
].join("; ");

function contentSecurityPolicy(): Plugin {
  return {
    name: "mathengine-content-security-policy",
    transformIndexHtml: {
      order: "pre",
      handler(html, context) {
        if (context.server) return html;
        return html.replace("<!--CSP-->", `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
      },
    },
  };
}

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
  },
  renderer: {
    root: resolve("src/renderer"),
    plugins: [react(), contentSecurityPolicy()],
    build: { minify: true, rollupOptions: { input: resolve("src/renderer/index.html") } },
  },
});
