# MathEngine: project context

This document is for developers and for AI assistants working on this repository. It records the goals,
the rules that must not be broken, how the system is built, what is verified, and what is still open.
Keep it current when the design changes. Setup and run commands are in `README.md`.

## 1. Goal

A desktop app for teaching math and physics. A central **knowledge engine** is the source of truth for
lessons, explanations, worked examples, and answer checks. The user interface is a thin layer over it.

## 2. Non-negotiable rules

These come from the project spec. Do not weaken them without an explicit decision from the project owner.

1. **Knowledge engine is the source of truth.** Lesson text, explanations, and answers live in
   `knowledge/*.yaml`. The frontend must not hardcode lessons or explanations.
2. **Math uses SymPy, with no arbitrary evaluation.** No `eval`, `exec`, or user- or model-supplied Python.
   Student and model input is parsed as data: an expression is parsed by a restricted parser into SymPy
   objects, or it is rejected.
3. **Ollama is non-authoritative.** Local AI may help phrase text. It never decides whether an answer is
   correct and never becomes knowledge by itself.
4. **Unverified AI content must never enter the authoritative index.** Met. See section 8.
5. **User progress is separate from the rebuildable index.** Progress lives in `data/user/progress.sqlite`.
   Rebuilding the index (`data/generated/knowledge.sqlite`) cannot delete progress.
6. **Stable IDs.** Concept IDs (for example `arithmetic.multiplication.facts`) and exercise IDs
   (for example `seven-times-eight`) are permanent. Progress refers to them. Renaming one is a migration,
   not an edit.
7. **Electron security.** Context isolation on, `nodeIntegration` off, sandbox on. The page reaches the
   backend only through one preload function, and every request is checked against an allowlist in the
   main process. Each request is also checked for its sender: only the app's own top-level page may send
   one. Section 9 lists the rules. Tests: `desktop/tests/main`, `desktop/tests/preload`, and
   `desktop/tests/renderer/isolation.test.ts`.
8. **Local only.** The app does not depend on any remote AI API. The backend binds to `127.0.0.1`.
9. **Windows first.** Documentation must include Windows commands.
10. **Build infrastructure before content.** Do not fill the library with large volumes of unverified content.

## 3. Repository layout

```
knowledge/                      Source records (YAML), one concept per file, grouped by subject
  arithmetic/  algebra/  calculus/
backend/
  requirements.txt              Runtime deps (fastapi, uvicorn, sympy, pyyaml, httpx)
  requirements-dev.txt          Adds pytest
  mathengine/
    config.py                   Settings from env vars (paths, Ollama URL/model)
    errors.py                   Error types, mapped to HTTP codes in api/app.py
    cli.py                      `validate` and `build-index` commands
    knowledge/
      models.py                 Pydantic schema for records (extra="forbid")
      loader.py                 Four-layer validation (section 5)
      index.py                  Builds the generated SQLite index atomically
      store.py                  Read-only in-memory view of an index; refuses the wrong kind of index
      retrieval.py              Term-based search with four explicit outcomes (section 6)
      views.py                  Shapes concept data for API responses (hides answers and hints)
      text.py                   Text normalisation for search
    math/
      expressions.py            Restricted parsing of expression strings into SymPy
      checker.py                Deterministic answer checking by named method (section 4)
      evaluate.py               Exact evaluation of one typed expression
    learning/
      progress.py               User-progress database (attempts, hints)
      service.py                Check/hint orchestration; writes progress
    ai/
      ollama.py                 Optional local Ollama client. Checks the shape of every response; failures become readable errors
      actions.py                Allowlisted actions only (no shell, file, or DB access)
    api/
      app.py                    FastAPI factory; binds to 127.0.0.1 by convention
      routes.py                 HTTP endpoints (section 7)
desktop/
  electron.vite.config.ts       Build config; injects the CSP into production HTML only
  src/main/index.ts             Electron main process: window, startup checks, IPC sender check, navigation
  src/main/security.ts          Security policy as pure functions (no Electron imports, unit-tested)
  src/main/backendProxy.ts      Forwards validated requests to the loopback backend, with a 10 s timeout
  src/preload/index.ts          The one bridge: window.mathengine.request
  src/shared/                   Route allowlist, API types, and the IPC channel name
  src/renderer/                 React UI (App, SearchPanel, ConceptView, StatusBar)
  scripts/verify-build.mjs      Checks the built preload, main, and renderer files (run by npm run check)
  tests/                        Vitest: shared, main, preload, renderer, and live-backend integration
tests/                          pytest suite for the backend (includes test_architecture.py)
data/generated/                 Rebuildable index. Not committed.
data/user/                      User progress. Not committed. Never rebuilt.
```

## 4. Math checking

`math/checker.py` runs one **explicit method** per exercise. The method is named in the record:

| Method | Meaning |
|--------|---------|
| `exact_numeric` | The student's number must equal the stored number exactly. |
| `symbolic_equivalence` | The student's expression must equal the stored expression for all values. |
| `derivative` | The student's expression must equal the SymPy derivative of a stored function. |
| `solve_equation` | The student's value must satisfy a stored equation. |
| `none` | No automatic method. The result is reported as **unverifiable**. |

Honesty rule: a result is marked correct or incorrect, with `verified: true`, only when a deterministic
method reaches a conclusion. Otherwise the response says no verdict was given. The UI never implies a
judgment it cannot back up.

Known limit: `symbolic_equivalence` tests equality over all real values. Some identities that hold only
for positive values, such as `(a^m)^n = a^(m*n)`, fail that test. A new record that needs a positive-domain
identity must not use `symbolic_equivalence` for it until a method that states its domain exists.

## 5. Knowledge records

### 5.1 Schema (schema_version 1)

One concept per YAML file in `knowledge/<subject>/`. Main fields:

- `id`: concept ID, `<subject>.<topic>.<subtopic>` in lowercase, with the first segment equal to `subject`.
- `title`, `aliases`, `keywords`, `subject`, `topic`, `subtopic`, `difficulty` (1 to 10), `summary`,
  `definition`
- `prerequisites`, `related`: other concept IDs. They must resolve, and prerequisites must not form cycles.
- `explanations`: levels `intro`, `standard`, `advanced`
- `formulas`: name, expression, optional result, variables, conditions
- `worked_examples`: problem, steps, answer
- `misconceptions`: description, explanation, correction
- `exercises`: id, prompt, `answer_type`, `check` (method and expected value), `hints`, feedback
- `sources`: title and kind
- `provenance`: origin, author, created date, and `ai_model` where AI wrote it
- `verification.status`: `ai_draft`, `reviewed`, or `verified`
- `version`: semantic version

Every model uses `extra="forbid"`, so a misspelled field is an error, not a silent skip.

### 5.2 Trust levels

- `ai_draft`: written or proposed by AI and not reviewed by a person. Never written to the authoritative
  index. It appears only in the developer preview index, on explicit request.
- `reviewed`: checked by a human. Exercise answers are still machine-checked on every build.
- `verified`: reviewed, and every exercise has a machine-checkable answer (no `none` checks).

### 5.3 Validation (`knowledge/loader.py`)

Four layers. Any error stops an index build, so a bad record can never replace a good index:

1. YAML syntax
2. Schema (types, ranges, required fields, extra fields)
3. Structure: file location matches subject, IDs unique, references resolve, no prerequisite cycles
4. Mathematics: formulas parse, stated identities hold, every stored answer agrees with its check

### 5.4 Seed content

Five records, all `ai_draft`, all valid. Because none is reviewed, the authoritative index is empty and the
student-facing library has no lessons yet:

- `arithmetic.multiplication.facts`: multiplication facts (difficulty 2), with exercises
  `seven-times-eight`, `eight-times-nine`, and `simplify-with-y`
- `arithmetic.multiplication.repeated-addition`: prerequisite for the facts
- `algebra.exponents.laws`
- `algebra.equations.linear-one-variable`
- `calculus.derivatives.power-rule`: the advanced concept

These are schema examples. They are not reviewed teaching content.

## 6. Index and retrieval

`knowledge/index.py` writes two files, each to a temporary file that replaces the old one only after success:

- `data/generated/knowledge.sqlite`: the **authoritative** index. Reviewed and verified records only.
- `data/generated/knowledge-dev.sqlite`: the **developer preview** index. All records, drafts included. Opened
  only when a request asks for drafts.

Both refuse to build when validation fails. The authoritative build also refuses when a reviewed record links
to a draft (section 8). Indexes hold concepts, term rows, and metadata. They never hold user progress.

`knowledge/store.py` opens the index once and keeps it in memory. It keeps the file closed while the app
runs, which matters on Windows, where a file cannot be replaced while open. After a rebuild, restart the
backend or call `POST /api/knowledge/reload`.

`knowledge/retrieval.py` finds concepts for a free-text request. Terms are looked up in the index and scored
by where they matched: title, then alias, keyword, topic, and body. It returns one of four outcomes and never
guesses silently. Search results contain no information about drafts:

- `matches`: one or more concepts clearly match
- `ambiguous`: several match about equally well. The UI asks the user to choose.
- `insufficient`: nothing trustworthy matches. The response says so.
- `needs_clarification`: the request has no topic words (for example, "I don't understand")

Search is keyword and structure based. There is no embedding or semantic search yet.

## 7. API

Base: `http://127.0.0.1:8000/api`. Local only.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | Status, version, index state, reviewed concept count, excluded draft count, whether the developer preview index exists |
| GET | `/ollama/status` | Whether Ollama is reachable and the configured model is installed. Always returns 200. A malformed or HTTP-error response from Ollama gives `reachable: false` with the reason |
| GET | `/subjects` | Subjects with concept counts |
| GET | `/concepts?q=&subject=&include_drafts=` | Search |
| GET | `/concepts/{id}?include_drafts=` | Concept detail. Exercise answers and hints are not returned |
| POST | `/exercises/check` | Body: concept_id, exercise_id, answer, include_drafts |
| POST | `/exercises/hint` | Body: concept_id, exercise_id, hint index, include_drafts |
| POST | `/math/evaluate` | Exact evaluation of one expression. Parsed, never executed |
| GET | `/progress/summary` | Attempt summary from the progress database |
| GET | `/actions`, POST `/actions/{name}` | Allowlisted actions for the assistant. Not exposed to the desktop app |
| POST | `/knowledge/reload` | Reopen the index after a rebuild. Not exposed to the desktop app |

`include_drafts` defaults to `false`. Without it, reads and checks use only the authoritative index, so a draft
concept returns 404. With `include_drafts=true`, they use the developer preview index. If that index has not
been built, the response is 503 with the rebuild instruction. Search results never mention drafts.

## 8. Draft handling (decided)

Rule 4 is met. The authoritative index (`data/generated/knowledge.sqlite`) never contains unreviewed AI
content. The build enforces this three ways:

1. **Exclusion.** The authoritative build writes reviewed and verified records only. A test checks that
   draft IDs and titles do not appear anywhere in the file's bytes.
2. **Refusal on links.** A reviewed record that lists a draft as a prerequisite or related concept makes the
   authoritative build fail. The student-facing index would otherwise point at content it does not contain.
3. **Refusal on the wrong file.** Each index stores `draft_content` (`excluded` or `included`). The store
   refuses to open the authoritative file as a preview, or the preview file as authoritative. An index from
   an older build, with no `draft_content` key, is refused as well.

Drafts are previewed through a separate **developer preview index** (`data/generated/knowledge-dev.sqlite`). It
holds every record, is opened only when a request sets `include_drafts=true`, and is labelled as
non-authoritative in its metadata. The assistant runs only on the authoritative index. Search results never
report how many drafts exist.

Consequence: until a reviewer approves a record, the student-facing library is empty. This is intended. The
project does not mark drafts as reviewed to fill it.

Note on the earlier design: the first milestone 1 build wrote drafts into the authoritative file behind a flag.
That was a spec violation and has been replaced by the scheme above.

## 9. Desktop app

- **Process model:** Electron main process owns the window and the only route to the backend.
- **Window:** `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, `webviewTag: false`,
  `webSecurity: true`. New windows are denied. `will-attach-webview` is blocked. Navigation and redirects
  away from the app page are prevented.
- **Sender check:** an IPC request is accepted only from the top-level app page (`parent === null`) at the
  app's own `file://` URL, or at the dev-server origin in development. Iframes and foreign pages get a
  refusal and never reach the backend.
- **Permissions:** every browser permission request is denied, and every permission check returns false.
- **Startup:** an invalid `MATHENGINE_BACKEND_URL` or a failed Electron start shows an error dialog and quits.
  The app does not start silently with a bad backend address.
- **Window re-creation (macOS "activate"):** re-creates the window without registering the IPC handler again.
- **Bridge:** preload exposes only `window.mathengine.request(request)`, which sends an IPC message on
  `mathengine:request` (the constant is in `src/shared/ipc.ts`).
- **Allowlist:** `src/shared/backendRoutes.ts` validates every request in the main process. Only the read,
  check, hint, and evaluate routes listed in section 7 pass. Admin and action routes are refused. Concept IDs
  are checked for path tricks. Query strings are restricted to a small character set. Bodies are capped at
  16 KB. Requests time out after 10 s.
- **Backend URL:** `MATHENGINE_BACKEND_URL`, default `http://127.0.0.1:8000`. Must be an `http://` loopback
  address.
- **CSP:** the production build injects a Content-Security-Policy meta tag: `default-src 'self'`,
  `script-src 'self'`, `connect-src 'none'`, `object-src 'none'`, and related restrictions. Scripts load
  from the bundle only.
- **Verdict display:** a verified result shows "Checked by the math engine." An unverifiable result shows
  "No verdict given" and says the answer is not marked right or wrong.
- **Developer mode:** a toggle sends `include_drafts=true`. Draft content is labelled "AI draft" with a banner.
- **Content:** the UI renders whatever the backend returns. It contains no lesson text.

## 10. Verification status

Last run on the working branch (commands in `README.md`):

| Check | Result |
|-------|--------|
| `pytest` (backend, API, Ollama failure modes, architecture guard) | 200 passed, 1 non-failing warning from the Starlette/httpx test client |
| `validate` and `build-index` (run from `backend/`) | 5 records valid. Authoritative index: 0 reviewed concepts, 5 drafts excluded. Developer preview index: 5 concepts, all drafts |
| Desktop `npm run check` (typecheck, `vitest`, `electron-vite build`, `verify:build`) | exit 0. `vitest`: 85 tests pass, none skipped, including mocked-Electron main and preload tests, the renderer isolation check, and UI tests against the running backend |
| Desktop `verify:build` | passes. Preload requires only `electron`. Main requires only `electron` and `node:path`/`node:url`. Renderer CSP is present, with `connect-src 'none'` and no inline script |

Tests cover schema rejection of bad records, loader and structure validation, retrieval outcomes, checker
methods and honesty rules, the API (including draft visibility), progress separation, Ollama failure modes,
allowlisted actions, the route allowlist, the Electron window policy and IPC sender check, and the React UI
against the real backend. The architecture guard fails if `math/`, `learning/`, or `knowledge/` imports `ai/`,
`api/`, or `httpx`.

**Electron security tests check that they can fail.** The main-process tests load the real `src/main/index.ts`
with a mocked `electron` module. Twelve deliberate weakenings were each applied and reverted, and every one
was caught by a failing test: `contextIsolation` off, `sandbox` off, `nodeIntegration` on, the sender
`parent === null` check removed, the sender check disabled, the permission deny removed (and the
request and check handlers flipped to allow), the navigation guard removed, the webview block removed, and
the window-count guard on `activate` removed.

**Ollama parser fixes, with evidence:**

- Before this round, a valid JSON body that was not an object (for example `["a"]`) made `status()` or
  `generate()` raise an uncaught `AttributeError`, which the API returned as HTTP 500. Now every shape is
  checked. 20 of the new `test_ollama_failures.py` tests fail against the old `ollama.py` and pass against the new one.
- End-to-end over real HTTP: a fake Ollama that returned a JSON array from `/api/tags` and HTTP 500 from
  `/api/generate` was run with the real backend (uvicorn). `/api/ollama/status` returned HTTP 200 with
  `reachable: false` and the reason. `/api/health`, `/api/subjects`, `/api/concepts`, and `/api/math/evaluate`
  all worked. The Python `generate()` call raised the typed `OllamaUnavailableError` for the 500.

**Fixed this round:** the README's CLI commands (`python -m mathengine.cli ...`) failed when run from the
repository root, because `mathengine` is inside `backend/`. They now run from `backend/`.

**Browser check of the production renderer (headless Chromium 131, outside the repo):**

- The built `desktop/out/renderer` was served and driven in headless Chromium under its production CSP. No
  console errors, no page errors, and no CSP violations.
- Flow verified: connected status; empty-library welcome; default search hides drafts; developer mode shows the
  draft banner; a verified answer check shows "Correct." and "Checked by the math engine."
- `window.mathengine` was a test shim that forwarded to the repo's real main-process proxy (validation,
  allowlist, timeouts), which called the live backend.
- A negative control (same CSP, deliberate inline script) confirmed that violations are detected, so the
  clean result is meaningful.

**Not verified:**

- **The Electron window has not been launched.** The Electron binary is hosted on GitHub's release storage
  (`objects.githubusercontent.com`). In this build sandbox that host fails the TLS handshake, so the binary cannot
  be downloaded, and no unofficial binary was used. The mocked-`electron` tests check the code that configures
  Electron, not Electron itself. Still needed on Windows: run the backend, then `npm run dev` in `desktop/`,
  and confirm the window loads, the status panel reads "connected", and a check works.
- **Ollama has not been tested with a live model.** It is not installed in the build sandbox, and `ollama.com`
  is outside its network allowlist. Its HTTP behavior was tested with `httpx.MockTransport` and one fake server.
  The `/api/tags` and `/api/generate` shapes were checked against the official Ollama API documentation.
- **Windows commands** have not been run on Windows. They follow the same steps as the Linux run.
- **Electron preload and main code are not run in a real renderer.** The browser check above used a test shim in
  place of `window.mathengine`.

## 11. Known limitations

- Search is keyword and structure based. Students must use words the index knows (aliases, keywords).
- Progress is recorded per attempt. There is no summary UI beyond the API.
- The Electron app is a shell: search, read, check, and hint. There is no lesson-planning or
  assistant UI yet.
- The library has only five draft seed records, and no reviewed content.

## 12. Next milestone (proposed)

**Milestone 2: content pipeline and review.**

1. Add a review workflow: a CLI command or PR template that promotes a record from `ai_draft` to
   `reviewed`, and checks that every exercise has a machine check. Promotion must be a human decision and
   must record who reviewed it.
2. Add a small set of reviewed multiplication and physics records, written and checked by a person.
3. Add a progress view in the desktop app that reads `/progress/summary`.
4. Test the Electron app manually on Windows and record the result here. Also run it once with a real
   Ollama model, and record the model name, its size, and the response time.

Milestone 2 starts only after milestone 1 is accepted.
