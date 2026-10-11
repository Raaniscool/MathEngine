// Verifies the production build output in out/. Run after `electron-vite build`.
// It checks the security properties that can be read from the built files:
//   - the preload bundle requires only "electron" (no bundled Node code or file access)
//   - the main bundle requires only "electron" and a short list of Node path/URL helpers
//   - the renderer page carries the Content-Security-Policy and has no inline scripts
//   - the renderer bundle does not require Electron or Node modules
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const OUT = join(import.meta.dirname, "..", "out");
const failures = [];

function read(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    failures.push(`missing build output: ${path} (run npm run build first)`);
    return "";
  }
}

function requiresOf(source) {
  return [...source.matchAll(/require\(\s*["']([^"']+)["']\s*\)/g)].map((match) => match[1]);
}

function assertOnly(label, source, allowed) {
  const found = requiresOf(source);
  const bad = found.filter((name) => !allowed.includes(name));
  if (bad.length) failures.push(`${label} requires disallowed modules: ${bad.join(", ")}`);
  console.log(`${label}: requires [${[...new Set(found)].join(", ")}]`);
}

const preload = read(join(OUT, "preload", "index.js"));
assertOnly("preload", preload, ["electron"]);

const main = read(join(OUT, "main", "index.js"));
assertOnly("main", main, ["electron", "node:path", "node:url", "path", "url", "node:fs", "fs"]);

const html = read(join(OUT, "renderer", "index.html"));
const csp = html.match(/Content-Security-Policy" content="([^"]+)"/)?.[1] ?? "";
for (const directive of ["default-src 'self'", "script-src 'self'", "connect-src 'none'", "object-src 'none'"]) {
  if (!csp.includes(directive)) failures.push(`renderer CSP is missing "${directive}"`);
}
if (/unsafe-eval/.test(csp)) failures.push("renderer CSP allows unsafe-eval");
if (/<script(?![^>]*\bsrc=)[^>]*>/.test(html)) failures.push("renderer HTML contains an inline script");
console.log(`renderer CSP: ${csp}`);

const assetsDir = join(OUT, "renderer", "assets");
for (const name of readdirSync(assetsDir)) {
  const path = join(assetsDir, name);
  if (!statSync(path).isFile() || !name.endsWith(".js")) continue;
  const source = readFileSync(path, "utf8");
  if (requiresOf(source).length) failures.push(`renderer bundle ${name} contains require() calls`);
  if (/require\(\s*["']electron["']\s*\)/.test(source)) failures.push(`renderer bundle ${name} imports electron`);
}

if (failures.length) {
  console.error("Build verification FAILED:\n  - " + failures.join("\n  - "));
  process.exit(1);
}
console.log("Build verification passed.");
