import { useEffect, useState } from "react";
import type { ConceptDetail, HealthResponse, OllamaStatusResponse, SearchResponse } from "../../shared/apiTypes";
import { api, describeFailure } from "./api";
import { ConceptView } from "./components/ConceptView";
import { SearchPanel } from "./components/SearchPanel";
import { StatusBar } from "./components/StatusBar";

function errorText(failure: unknown): string {
  return failure instanceof Error ? failure.message : describeFailure({ ok: false, status: 0, data: null, error: String(failure) });
}

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [ollama, setOllama] = useState<OllamaStatusResponse | null>(null);
  const [ollamaError, setOllamaError] = useState<string | null>(null);
  const [includeDrafts, setIncludeDrafts] = useState(false);
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [concept, setConcept] = useState<ConceptDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch((failure) => setHealthError(errorText(failure)));
    api.ollamaStatus().then(setOllama).catch((failure) => setOllamaError(errorText(failure)));
  }, []);

  async function search(query: string, subject: string) {
    setBusy(true);
    setPageError(null);
    try {
      setSearchResult(await api.search(query, { subject: subject || undefined, includeDrafts }));
    } catch (failure) {
      setPageError(errorText(failure));
    } finally {
      setBusy(false);
    }
  }

  async function open(conceptId: string) {
    setPageError(null);
    try {
      setConcept(await api.concept(conceptId, includeDrafts));
    } catch (failure) {
      setPageError(errorText(failure));
    }
  }

  return (
    <main className="app">
      <header className="app-header">
        <h1>MathEngine</h1>
        <label className="dev-toggle">
          <input type="checkbox" checked={includeDrafts} onChange={(event) => setIncludeDrafts(event.target.checked)} />
          Developer mode: show unreviewed AI drafts
        </label>
      </header>

      <StatusBar health={health} healthError={healthError} ollama={ollama} ollamaError={ollamaError} />

      {pageError && <p className="error">{pageError}</p>}

      <div className="layout">
        <SearchPanel result={searchResult} busy={busy} onSearch={search} onOpen={open} />
        <div className="content">
          {concept ? (
            <ConceptView concept={concept} includeDrafts={includeDrafts} onOpen={open} />
          ) : (
            <section className="panel">
              <h2>Welcome</h2>
              {health?.knowledge.index_built && health.knowledge.concept_count === 0 && !includeDrafts ? (
                <p>
                  No reviewed lessons are published yet. Lessons appear here once a reviewer approves them.
                  Developer mode can preview unreviewed AI drafts.
                </p>
              ) : (
                <p>
                  Search for a concept, such as <em>multiplication facts</em> or <em>power rule</em>. Lessons, hints
                  and answer checks all come from the knowledge library on the backend.
                </p>
              )}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
