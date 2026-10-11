/**
 * Static boundary check: renderer code must reach the outside world only through window.mathengine.
 * It must not import Electron or Node.js, and it must not call fetch or other network APIs directly,
 * because the production CSP sets connect-src 'none'.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const RENDERER = join(__dirname, "../../src/renderer");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx|html|css)$/.test(name) ? [path] : [];
  });
}

const FORBIDDEN: Array<[string, RegExp]> = [
  ["imports electron", /from\s+["']electron["']|require\(\s*["']electron["']\s*\)/],
  ["uses Node.js builtins", /require\(\s*["'](node:)?[a-z_/]+["']\s*\)|from\s+["'](node:)?(fs|path|child_process|os|net|http|https)["']/],
  ["touches process or globals of Node", /\bprocess\.|\bBuffer\b|__dirname|__filename/],
  ["calls the network directly", /\bfetch\s*\(|new\s+XMLHttpRequest|new\s+WebSocket|navigator\.sendBeacon/],
  ["uses eval-like APIs", /\beval\s*\(|new\s+Function\s*\(/],
];

// Removes block and line comments, so prose such as "Electron main process." is not treated as code.
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "$1");
}

describe("renderer isolation", () => {
  const files = sourceFiles(RENDERER);

  it("finds the renderer sources", () => {
    expect(files.length).toBeGreaterThan(5);
  });

  for (const [label, pattern] of FORBIDDEN) {
    it(`does not ${label}`, () => {
      const offenders = files.filter((file) => pattern.test(code(readFileSync(file, "utf8"))));
      expect(offenders.map((file) => relative(RENDERER, file))).toEqual([]);
    });
  }

  it("reaches the backend only through window.mathengine", () => {
    const api = readFileSync(join(RENDERER, "src/api.ts"), "utf8");
    expect(api).toContain("window.mathengine");
  });
});
