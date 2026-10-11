# MathEngine

A desktop app for teaching math and physics. A central **knowledge engine** is the source of truth:
every lesson, explanation, and answer check comes from version-controlled records in `knowledge/`
and deterministic math in SymPy. Local AI (Ollama) is optional and never authoritative.

This README covers setup and running. For architecture, design rules, and status, see
[`MATHENGINE_PROJECT_CONTEXT.md`](MATHENGINE_PROJECT_CONTEXT.md).

**Initial target: Windows.** Commands for Windows (PowerShell) come first. Linux/macOS equivalents
are in brackets.

## What you need

| Tool | Version | Used for |
|------|---------|----------|
| Python | 3.11 or newer | Backend, tests |
| Node.js | 20.19+ or 22.12+ (LTS) | Desktop app (Electron + React) |
| Git | any recent | Cloning |
| Ollama | optional | Local AI helper. Not required; the app works without it |

## 1. Set up the backend (Python)

Run these from the repository root (the folder that contains `README.md`).

```powershell
# Windows (PowerShell)
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

```bash
# Linux / macOS
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

## 2. Build the knowledge index

The index (`data/generated/knowledge.sqlite`) is generated from the YAML records in `knowledge/`.
It is never committed. Rebuild it whenever you change a record.

```powershell
# Windows
backend\.venv\Scripts\python.exe -m mathengine.cli validate
backend\.venv\Scripts\python.exe -m mathengine.cli build-index
```

```bash
# Linux / macOS
backend/.venv/bin/python -m mathengine.cli validate
backend/.venv/bin/python -m mathengine.cli build-index
```

`validate` checks every record and reports every error. `build-index` runs the same checks first
and refuses to replace the index if any record is invalid.

## 3. Run the tests

```powershell
# Windows: backend tests (schema, retrieval, math checking, API, CLI)
backend\.venv\Scripts\python.exe -m pytest
```

```bash
# Linux / macOS
backend/.venv/bin/python -m pytest
```

Expected: all tests pass. Desktop tests are in step 5.

## 4. Start the backend

The backend listens on `127.0.0.1:8000`, so only this computer can reach it.

```powershell
# Windows: run from the backend folder, in its own terminal window
cd backend
.venv\Scripts\uvicorn.exe mathengine.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
# Linux / macOS
cd backend
.venv/bin/uvicorn mathengine.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Check it in a browser or with PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Expected: `status` is `ok`, and `knowledge.index_built` is `true`.

## 5. Set up and run the desktop app (Electron)

Keep the backend from step 4 running in its own terminal.

```powershell
# Windows
cd desktop
npm install
npm run check      # typecheck + tests + production build
npm run dev        # starts the Electron window
```

```bash
# Linux / macOS
cd desktop
npm install
npm run check
npm run dev
```

The window shows a connection status panel. If the backend is not running, the panel says
so and gives the address it tried.

To point the desktop app at a different local port, set `MATHENGINE_BACKEND_URL` before `npm run dev`
(for example `$env:MATHENGINE_BACKEND_URL="http://127.0.0.1:8001"` in PowerShell). Only loopback
`http://` addresses are accepted.

### Optional: local AI with Ollama

Ollama is optional. The app works without it, and the status panel reports when it is not running.
To try it:

```powershell
ollama pull qwen2.5:1.5b
```

The model name is set by `MATHENGINE_OLLAMA_MODEL`. The default is `qwen2.5:1.5b`, which is a starting
point, not a chosen model. Ollama output is never shown as a verified answer.

## Developer mode: unreviewed AI drafts

All seed records are `ai_draft` (AI-written, not yet reviewed by a person). They are hidden from
normal search and lessons. To view them, turn on **Developer mode: show unreviewed AI drafts** in the
app. Draft content is then labelled "AI draft" and shown with a banner. Checks and hints for draft
exercises only work when this mode is on.

## Project layout

```
knowledge/        Version-controlled knowledge records (YAML), one concept per file, by subject
backend/          Python: schema, loader, index, retrieval, SymPy checker, FastAPI API, progress
desktop/          Electron + React + TypeScript app (electron-vite)
tests/            pytest suite for the backend
data/generated/   Generated index. Not committed. Rebuild with build-index
data/user/        User progress database. Not committed. Never deleted by index rebuilds
```

## Troubleshooting

- **"Backend is not reachable"**: start the backend (step 4). Check the port and that no other program uses it.
- **Draft exercise returns 404**: turn on Developer mode, or the draft is hidden as intended.
- **`build-index` refuses to run**: run `validate` and fix the reported record errors first.
- **Backend running old code after edits**: restart uvicorn. It does not reload automatically.
- **`npm install` fails on Node versions older than 20.19**: upgrade Node.js.
- **Electron download blocked behind a proxy or firewall**: Electron downloads its binary during
  `npm install`. Set your proxy settings, or retry from a network that can reach GitHub releases.

## Status

Milestone 1 is the foundation: backend, knowledge schema and retrieval, math checking, and a desktop
shell that talks to the backend. See `MATHENGINE_PROJECT_CONTEXT.md` for what is verified and what is not.
