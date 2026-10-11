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
  index. It appears only in the developer preview index, on explicit request. **All 31 current records are
  `ai_draft`.** The authoritative index is therefore empty, and the default app shows no lessons.
- `reviewed`: checked by a human. Exercise answers are still machine-checked on every build. Needs
  `reviewed_by` and `reviewed_on`. No record has this status yet.
- `verified`: reviewed, and every exercise has a machine-checkable answer (no `none` checks). Same fields.
- `machine_checked`: **in the schema, not approved.** Every exercise answer and formula identity passed the
  deterministic SymPy checker, and the record carries `checked_by` and `checked_on`. Its text was not reviewed
  by a person. The label must say so. It would be included in the authoritative index. **Pending decision:**
  the project owner must accept or reject this tier (section 12). If rejected, remove the tier from
  `models.py` and set those records back to `ai_draft`.

### 5.3 Validation (`knowledge/loader.py`)

Four layers. Any error stops an index build, so a bad record can never replace a good index:

1. YAML syntax
2. Schema (types, ranges, required fields, extra fields)
3. Structure: file location matches subject, IDs unique, references resolve, no prerequisite cycles
4. Mathematics: formulas parse, stated identities hold, every stored answer agrees with its check

### 5.4 Library content

31 records, all `ai_draft`, all valid (`python -m mathengine.cli validate`):

| Subject | Records | Status |
|---------|--------:|--------|
| arithmetic | 23 | all `ai_draft` |
| algebra | 5 | all `ai_draft` |
| geometry | 2 | all `ai_draft` |
| calculus | 1 | `ai_draft` |
| **Total** | **31** | **0 reviewed, 31 `ai_draft`** |

Before this round there were 5 seed drafts (2 arithmetic, 2 algebra, 1 calculus). 26 records were added. Two
seed records (`multiplication-facts`, `multiplication-repeated-addition`) were rewritten.

Arithmetic covers counting and place value, addition, subtraction, multiplication facts and repeated addition,
division basics, long division, factors, multiples, primes, divisibility, equivalent fractions, fraction
add/subtract/multiply/divide, decimal place value and operations, percentages, ratios and rates, integers
(add/subtract and multiply/divide), order of operations, and powers. Algebra covers exponent laws,
linear equations in one variable, evaluating expressions, like terms, and the distributive property. Geometry
covers rectangle perimeter and area, and the triangle angle sum. Calculus has the power rule.

**Machine checks on each build.** Exercise answers, formula identities, and worked-example arithmetic are checked
with SymPy. Worked-example steps are checked only when they are pure number chains (for example `6 x 10 = 60`).
Prose steps, steps with variables, and symbolic answers are **not** machine-checked, and the docs must not
claim that they are.

**Not yet written:** two-step equations, inequalities, the rest of pre-algebra, most of geometry and
measurement, and other subjects. Each new record is written in small batches. It is re-read, run through
`validate`, and only then counted as done.

## 6. Index, retrieval, and the assistant

### 6.1 Indexes

`knowledge/index.py` writes two files, each to a temporary file that replaces the old one only after success:

- `data/generated/knowledge.sqlite`: the **authoritative** index. Reviewed and verified records only. Empty
  until a person approves a record (or until the `machine_checked` decision in section 12 is made).
- `data/generated/knowledge-dev.sqlite`: the **developer preview** index. All records, drafts included. Opened
  only when a request asks for drafts.

Both refuse to build when validation fails. The authoritative build also refuses when a reviewed record links
to a draft (section 8). Indexes hold concepts, term rows, and metadata. They never hold user progress.

`knowledge/store.py` opens the index once and keeps it in memory. It keeps the file closed while the app
runs, which matters on Windows, where a file cannot be replaced while open. After a rebuild, restart the
backend or call `POST /api/knowledge/reload`.

### 6.2 Search (`knowledge/text.py`, `knowledge/retrieval.py`)

**Root cause of the earlier failure.** Searches for "multiplication facts" and "times tables" failed for several
reasons, and each was fixed at its source:

1. Only five seed records existed, all drafts, so the default index was empty and every search said nothing
   matched. That is a trust-policy outcome, not a search bug, and it is still the case (section 12).
2. "times" was stemmed to "time" before the synonym lookup, so it never reached "multiply".
3. Body-text mentions counted toward document frequency, so ordinary words such as "multiply" looked generic.
4. A title-only match and a topic-only match scored the same, so the best record could lose a tie to an
   alphabetically earlier one.
5. Typos such as "multiplcation" were not matched, because fuzzy matching ran against stemmed vocabulary.

**How it works now.** Nothing is special-cased for any topic.

- **Normalization** (applied to the record text at build time and to the query at search time, identically):
  lowercase, punctuation removed, accents folded, a light stemmer, and a synonym table (for example "times" →
  "multiply", "algebraic" → "algebra"). The raw word is checked against the synonym table before stemming.
  Single-character tokens, common stopwords, and request words (for example "teach", "explain", "practice", "help", "show") are dropped from the search terms. The request word still sets the intent (section 6.2 below).
- **Typo tolerance** matches the typed word against a lexicon of words the library uses.
- **Field weights.** A term can match the title (highest), an alias, a keyword, the topic or subject hierarchy,
  or the body text. Each record scores the best matching field plus 30% of the other matching fields.
- **IDF weighting.** A term that appears in many records counts for less. Document frequency counts only the
  title, aliases, keywords, and topic, not body text. Generic words (for example "number", "rule", "problem") are
  never used to pick a record.
- **Outcomes.** A query returns one of:
  - `matches`: one record clearly leads. An exact title or alias match always comes first.
  - `ambiguous`: several records are close, or the request is broad (no exact title or alias, and it fits
    three or more records). The response is a short question with up to three options, for example
    "teach me basic algebra" or "multiplication".
  - `insufficient`: nothing relevant. The response says so and offers up to three nearby topics. It never
    implies that hidden drafts exist.
  - `needs_clarification`: no topic words.
- **Subject filter** narrows the search to one subject.

**Intent** (`knowledge/query.py`, rules only, no model). Order: solve > practice > lesson > explain > search,
plus `clarify` when there is no topic:

| Input | Intent | What happens |
|-------|--------|--------------|
| `7 x 8`, `7 times 8`, `what is 2x + 3 = 7` | solve | SymPy checks the expression. Qwen is not used |
| `solve for x` | clarify | Asks for the equation |
| `I don't understand`, `help` | clarify | Asks what to explain |
| `practice fractions` | practice | Looks up the topic |
| `teach me long division` | lesson | Looks up the topic and returns the lesson text |
| `explain long division` | explain | Looks up the topic, keeping any expression |
| `multiplication facts` | search | Looks up the topic |

Equation solving is not implemented in the assistant. An equation gets a clear "not supported yet" answer.

**Developer mode** shows the retrieved record IDs and the intent reason. Ordinary users do not see them.

### 6.3 Assistant flow (`ai/assistant.py`, route `POST /api/assistant/ask`)

user input → intent (rules) → retrieval (index) → deterministic check (SymPy) → Qwen explains retrieved text only →
response with next steps.

1. **Intent** from section 6.2.
2. **Calculations** (`solve`) are checked with SymPy and returned as `status: verified`. Qwen is not called.
3. **Clarifications and not-found** return immediately. Qwen is not called.
4. **Matches**: at most two records are used, and each is cut to a share of 2,400 characters in total. The
   excerpt comes from `ContextBuilder`, which excludes drafts (unless developer mode), hints, and exercise
   answers. The bounded excerpt is the only library content Qwen sees. The whole library is never sent.
5. **Qwen** is called once with a fixed system prompt. The prompt says to use only the library text, to add no
   facts, numbers, or calculations, and to keep the answer short. The call uses `stream: false`.
6. **Guard.** Every simple two-number arithmetic claim in Qwen's reply (for example `7 x 8 = 56`) is re-checked
   with SymPy. If any claim is wrong, or cannot be decided, Qwen's text is withheld. The library text is shown
   instead, with the reason. The guard checks only those simple claims. It does not check every factual statement
   the model makes. That is a stated limitation.
7. **Response** contains the status, the verified library text with sources, next steps (prerequisites and
   related records, up to four), and a `qwen` block with its status.

**Qwen is never the source of mathematical truth.** It does not decide which records exist, does not decide
whether an answer is right, and cannot override a SymPy result or a verification status.

**Every model failure is visible and does not stop the answer.** `qwen.status` is one of:

| Status | Meaning | What the learner sees |
|--------|---------|-----------------------|
| `ok` | The model replied and the guard passed | The explanation, labelled as re-checked, plus the library text |
| `blocked` | The reply had a wrong or undecidable arithmetic claim | "The model's explanation was not shown", plus the library text |
| `unavailable` | Ollama not reachable, timeout, model not installed (with the `ollama pull` command), HTTP error, malformed JSON, or empty reply | The reason, plus the library text |
| `not_used` | The model was not needed (calculation, clarification, not found) | A short reason |

The app works fully without Qwen. The library answer, search, lessons, and calculations do not depend on it.

### 6.4 Qwen configuration (no code change needed)

| Variable | Default | Meaning |
|----------|---------|---------|
| `MATHENGINE_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server. Use the address where your Ollama runs |
| `MATHENGINE_OLLAMA_MODEL` | `qwen2.5:1.5b` | Model tag. **A starting point only.** Check `ollama list` and set the name you actually have |
| `MATHENGINE_OLLAMA_TIMEOUT` | `120` | Seconds to wait for one model reply. Invalid values fall back to 120 |

`GET /api/ollama/status` reports whether Ollama is reachable, whether the configured model is installed, and
the installed model names. If the configured model is missing but a Qwen model is installed, the message names
it. The backend never switches models by itself. Real-model tests are in `tests/test_real_ollama.py` and are
skipped unless `MATHENGINE_REAL_OLLAMA=1` is set. They use whatever model is configured.

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
| POST | `/assistant/ask` | Body: `question` (max 500 characters), `include_drafts`, `include_diagnostics`. Returns the answer, the verified library text, the Qwen status, and next steps. See section 6.3 |
| POST | `/knowledge/reload` | Reopen the index after a rebuild. Not exposed to the desktop app |

`include_drafts` defaults to `false`. Without it, reads, checks, and the assistant use only the authoritative
index, so a draft concept returns 404. With `include_drafts=true`, they use the developer preview index, and
the assistant labels its answer as possibly using drafts. If that index has not been built, the response is
503 with the rebuild instruction. Search results never mention drafts.

`/assistant/ask` is the only route that calls Ollama. Its request body is validated strictly, and unknown fields
are rejected with 422. The route waits up to 150 seconds on the desktop side, which is longer than the backend's
model timeout.

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
  16 KB. Requests time out after 10 s, except the assistant route, which times out after 150 s because it waits
  on a local model. The browser preview uses the same limits.
- **Backend URL:** `MATHENGINE_BACKEND_URL`, default `http://127.0.0.1:8000`. Must be an `http://` loopback
  address.
- **CSP:** the production build injects a Content-Security-Policy meta tag: `default-src 'self'`,
  `script-src 'self'`, `connect-src 'none'`, `object-src 'none'`, and related restrictions. Scripts load
  from the bundle only.
- **Verdict display:** a verified result shows "Checked by the math engine." An unverifiable result shows
  "No verdict given" and says the answer is not marked right or wrong.
- **Developer mode:** a toggle sends `include_drafts=true`. Draft content is labelled "AI draft" with a banner.
- **Connection status:** the status bar shows the backend (connected, version, reviewed concept count) and
  Ollama (running and model name, or the reason it is not ready).
- **Ask panel:** one question box. It shows a loading state with a time warning, a visible error for backend
  failures, a short clarifying question with clickable options, nearby topics when nothing matches, a verified
  calculation, the model's explanation (or why it was withheld or unavailable), the library text with sources,
  and next steps. Each answer's status is stated plainly.
- **Content:** the UI renders whatever the backend returns. It contains no lesson text and no math.

## 10. Verification status

Last run on the working branch (commands in `README.md`):

| Check | Result |
|-------|--------|
| `pytest -q` from the repository root | 249 passed, 1 skipped (real-model tests, skipped unless `MATHENGINE_REAL_OLLAMA=1`) |
| `validate` (run from `backend/`) | 31 records valid |
| `build-index` (run from `backend/`) | Authoritative: 0 reviewed concepts, 31 drafts excluded. Developer preview: 31 concepts, all drafts |
| Desktop `npm run check` (typecheck, `vitest`, build, `verify:build`) | 111 tests pass, build verified |
| Live check, running backend | Started the backend against a local stand-in for Ollama (a logging server, not a real model). The app sent exactly one `/api/generate` request with `stream: false`, the configured model, and a 1,478-character bounded prompt. The guard accepted the correct reply. With the stand-in stopped, the same question returned `qwen.status: unavailable` with the reason, and the library text was still returned |

Search results checked against the real library (developer mode, drafts on): "multiplication facts", "times
tables", "multiplcation facts", and "Multiplication, FACTS?" all return the multiplication-facts record first.
"multiplication" and "times 6" return a clarifying question that includes it. "fractions" returns a
clarifying question. "teach me basic algebra" returns a clarifying question across the algebra records, not one
arbitrary record. "power rule" and "derivatives" return the draft power-rule record only in developer mode.
"pizza" returns no match with nearby topics.

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
- **No live Qwen model was tested.** Ollama is not installed in the build sandbox, and `ollama.com` is outside
  its network allowlist. The assistant was tested with `httpx.MockTransport`, with a logging stand-in server, and
  against the official Ollama API shapes. The real-model tests in `tests/test_real_ollama.py` are written but
  have not been run against a real model. Run them on your machine with `MATHENGINE_REAL_OLLAMA=1`.
- **Windows commands** have not been run on Windows. They follow the same steps as the Linux run.
- **Electron preload and main code are not run in a real renderer.** The browser check above used a test shim in
  place of `window.mathengine`.

## 11. Known limitations

- **The default app shows no lessons.** Every record is an AI draft, so the authoritative index is empty, and a
  normal user gets "no reviewed material" for every question. This is the trust policy working as designed. It
  is the main decision still open (section 12).
- Search is keyword and structure based. There is no embedding or semantic search. Synonyms and typo tolerance
  are limited to the words in the library and in the synonym table.
- The assistant does not solve equations. It checks simple calculations with SymPy.
- The guard checks only simple two-number arithmetic claims in Qwen's reply. It does not verify other factual
  claims, so the explanation still depends on the model staying close to the excerpt. The excerpt is the
  verified source, and the library text is always shown next to the explanation.
- Worked-example steps are checked only when they are pure number chains. Prose, variables, and symbolic answers
  are not machine-checked.
- Progress is recorded per attempt. There is no summary UI beyond the API.
- The Electron app is a shell: search, read, check, hint, and ask. There is no lesson-planning UI yet.
- The library has 31 AI-draft records. Coverage is partial: it stops before two-step equations, inequalities,
  most of geometry and measurement, and other subjects.

## 12. Next milestone (proposed)

**Decision needed from the project owner before the default app can show any lesson:**

1. **Approve the `machine_checked` tier.** Records that pass every SymPy check would be included in the
   authoritative index. The UI would label them "checked by the math engine, text not reviewed by a person."
   This changes sections 5.2 and 6.1. If you reject it, the tier is removed from `models.py`, and records stay
   `ai_draft` until a person reviews them.
2. **Or review records by hand.** A reviewer changes `ai_draft` to `reviewed` (with `reviewed_by` and
   `reviewed_on`). This is slower but is the stricter option.
3. **Or show drafts in the default app with a clear label.** This would break the "drafts stay separate" rule.
   It is not recommended.

**Milestone 2: content pipeline and review.**

1. Add a review workflow: a CLI command or PR template that promotes a record from `ai_draft` to `reviewed`, and
   checks that every exercise has a machine check. Promotion must be a human decision and must record who
   reviewed it.
2. Finish the library in the priority order: two-step equations, inequalities, the rest of pre-algebra, geometry
   and measurement, then other subjects. Every record is re-read and run through `validate` before it counts.
3. Run the real-model tests on the owner's machine (`MATHENGINE_REAL_OLLAMA=1 pytest -q -m real_ollama`), and
   record the model name, its size, and the response time.
4. Test the Electron app manually on Windows and record the result here.
5. Add a progress view in the desktop app that reads `/progress/summary`.

Milestone 2 starts only after milestone 1 is accepted.
