import { useState } from "react";
import type { AssistantResponse } from "../../../shared/apiTypes";
import { api, describeFailure } from "../api";

interface Props {
  includeDrafts: boolean;
  onOpen: (conceptId: string) => void;
}

const MAX_QUESTION = 500;

function errorText(failure: unknown): string {
  return failure instanceof Error ? failure.message : describeFailure({ ok: false, status: 0, data: null, error: String(failure) });
}

/** Explains what the model did, in plain words. The library text is always the verified source. */
function QwenNote({ response }: { response: AssistantResponse }) {
  const qwen = response.qwen;
  switch (qwen.status) {
    case "ok":
      return (
        <div className="qwen ok">
          <h3>Explanation from the local model ({qwen.model})</h3>
          <p className="qwen-text">{qwen.text}</p>
          <p className="muted">Its arithmetic was re-checked with SymPy. The library text below is the source.</p>
        </div>
      );
    case "blocked":
      return (
        <div className="qwen warn" role="status">
          <strong>The model’s explanation was not shown.</strong> {qwen.error} The library text below still answers
          the question.
        </div>
      );
    case "unavailable":
      return (
        <div className="qwen warn" role="status">
          <strong>Language model unavailable.</strong> {qwen.error} The library text below still works without it.
        </div>
      );
    default:
      return qwen.reason ? <p className="muted">{qwen.reason}</p> : null;
  }
}

export function AskPanel({ includeDrafts, onOpen }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AssistantResponse | null>(null);

  async function ask(text: string) {
    const clean = text.trim();
    if (!clean) return;
    setQuestion(clean);
    setLoading(true);
    setError(null);
    try {
      setResponse(await api.ask(clean.slice(0, MAX_QUESTION), { includeDrafts }));
    } catch (failure) {
      setResponse(null);
      setError(errorText(failure));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel ask-panel" aria-label="Ask MathEngine">
      <h2>Ask MathEngine</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor="ask-input">Question or calculation</label>
        <div className="ask-row">
          <input
            id="ask-input"
            type="text"
            maxLength={MAX_QUESTION}
            value={question}
            placeholder="for example: multiplication facts, long division, or 7 x 8"
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>

      {loading && (
        <p className="loading" role="status" aria-live="polite">
          Looking up the library{includeDrafts ? " (including drafts)" : ""}. A local model may take up to two minutes.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {response && !loading && (
        <div className="ask-result" aria-live="polite">
          {response.status === "verified" && (
            <p>
              <strong>{response.expression}</strong> = <strong>{response.result}</strong>
              {response.approximate && response.approximate !== response.result ? ` (≈ ${response.approximate})` : ""}
              <span className="muted"> · checked by {response.verified_by}</span>
            </p>
          )}

          {(response.status === "clarify" || response.status === "not_found") && response.message && <p>{response.message}</p>}

          {response.status === "clarify" && response.options && response.options.length > 0 && (
            <div className="choices">
              {response.options.map((option) => (
                <button key={option.id} type="button" className="choice" onClick={() => void ask(option.title)}>
                  {option.title}
                </button>
              ))}
            </div>
          )}

          {response.status === "not_found" && response.suggestions && response.suggestions.length > 0 && (
            <div>
              <p className="muted">Nearby topics:</p>
              <div className="choices">
                {response.suggestions.map((option) => (
                  <button key={option.id} type="button" className="choice" onClick={() => onOpen(option.id)}>
                    {option.title}
                  </button>
                ))}
              </div>
            </div>
          )}

          {response.status === "answer" && (
            <>
              {response.includes_drafts && (
                <p className="draft-label">Developer mode: this answer may use unreviewed AI drafts.</p>
              )}
              <QwenNote response={response} />
              {response.library?.map((entry) => (
                <article key={entry.id} className="library-text">
                  <h3>From the library</h3>
                  <pre>{entry.text}</pre>
                  {entry.sources.length > 0 && <p className="muted">Sources: {entry.sources.join("; ")}</p>}
                </article>
              ))}
              {response.next_steps && response.next_steps.length > 0 && (
                <div>
                  <p className="muted">Next steps:</p>
                  <div className="choices">
                    {response.next_steps.map((step) => (
                      <button key={step.id} type="button" className="choice" onClick={() => onOpen(step.id)}>
                        {step.title}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {response.status === "unsupported" && response.message && <p>{response.message}</p>}

          {includeDrafts && response.retrieved_ids && (
            <p className="dev-ids">
              Retrieved record IDs: {response.retrieved_ids.length ? response.retrieved_ids.join(", ") : "none"} · intent{" "}
              {response.intent} ({response.intent_reason})
            </p>
          )}
        </div>
      )}
    </section>
  );
}
