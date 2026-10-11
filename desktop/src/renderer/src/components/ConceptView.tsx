import { useState } from "react";
import type { CheckResponse, ConceptDetail, HintResponse, PublicExercise } from "../../../shared/apiTypes";
import { api } from "../api";
import { DRAFT_NOTICE, describeVerdict } from "../verdict";

interface Props {
  concept: ConceptDetail;
  includeDrafts: boolean;
  onOpen: (conceptId: string) => void;
}

export function ConceptView({ concept, includeDrafts, onOpen }: Props) {
  const isDraft = concept.verification.status === "ai_draft";
  return (
    <article className="panel concept">
      {isDraft && <div className="draft-banner">{DRAFT_NOTICE}</div>}
      <header>
        <p className="muted">
          {concept.subject.replace(/_/g, " ")} › {concept.topic}
          {concept.subtopic ? ` › ${concept.subtopic}` : ""} · difficulty {concept.difficulty}/10
        </p>
        <h2>{concept.title}</h2>
        <p className="summary">{concept.summary}</p>
      </header>

      <section>
        <h3>Definition</h3>
        <p>{concept.definition}</p>
      </section>

      {concept.explanations.map((item) => (
        <section key={item.level}>
          <h3>{item.level === "intro" ? "Intuition" : item.level === "standard" ? "Explanation" : "Going deeper"}</h3>
          <p>{item.text}</p>
        </section>
      ))}

      {concept.formulas.length > 0 && (
        <section>
          <h3>Formulas</h3>
          <ul>
            {concept.formulas.map((formula) => (
              <li key={formula.name}>
                <strong>{formula.name}:</strong> <code>{formula.result ? `${formula.expression} = ${formula.result}` : formula.expression}</code>
                {formula.conditions.length > 0 && <span className="muted"> (if {formula.conditions.join("; ")})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {concept.worked_examples.map((example) => (
        <section key={example.title} className="example">
          <h3>Worked example: {example.title}</h3>
          <p>{example.problem}</p>
          <ol>
            {example.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p>
            <strong>Answer:</strong> {example.answer}
          </p>
        </section>
      ))}

      {concept.misconceptions.length > 0 && (
        <section>
          <h3>Common mistakes</h3>
          <ul>
            {concept.misconceptions.map((item) => (
              <li key={item.description}>
                <strong>{item.description}</strong> {item.correction}
              </li>
            ))}
          </ul>
        </section>
      )}

      {(concept.prerequisites.length > 0 || concept.related.length > 0) && (
        <section>
          <h3>Connections</h3>
          {concept.prerequisites.length > 0 && (
            <p>
              Before this:{" "}
              {concept.prerequisites.map((item) => (
                <button key={item.id} type="button" className="link" onClick={() => onOpen(item.id)}>
                  {item.title}
                </button>
              ))}
            </p>
          )}
          {concept.related.length > 0 && (
            <p>
              See also:{" "}
              {concept.related.map((item) => (
                <button key={item.id} type="button" className="link" onClick={() => onOpen(item.id)}>
                  {item.title}
                </button>
              ))}
            </p>
          )}
        </section>
      )}

      {concept.exercises.length > 0 && (
        <section>
          <h3>Practice</h3>
          {concept.exercises.map((exercise) => (
            <ExercisePanel
              key={exercise.id}
              conceptId={concept.id}
              exercise={exercise}
              includeDrafts={includeDrafts}
            />
          ))}
        </section>
      )}

      <footer className="provenance muted">
        Source: {concept.sources.map((source) => source.title).join("; ")} · version {concept.version} ·{" "}
        {concept.verification.status === "ai_draft" ? "AI-generated, not yet reviewed" : `status: ${concept.verification.status}`}
      </footer>
    </article>
  );
}

interface ExerciseProps {
  conceptId: string;
  exercise: PublicExercise;
  includeDrafts: boolean;
}

function ExercisePanel({ conceptId, exercise, includeDrafts }: ExerciseProps) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<CheckResponse | null>(null);
  const [hints, setHints] = useState<HintResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function check() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.checkAnswer(conceptId, exercise.id, answer, includeDrafts));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function nextHint() {
    setError(null);
    try {
      const hint = await api.hint(conceptId, exercise.id, hints.length, includeDrafts);
      setHints((previous) => [...previous, hint]);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }

  const verdict = result ? describeVerdict(result) : null;
  const hintsLeft = exercise.hint_count - hints.length;

  return (
    <div className="exercise">
      <p>{exercise.prompt}</p>
      <form
        className="answer-row"
        onSubmit={(event) => {
          event.preventDefault();
          if (answer.trim()) void check();
        }}
      >
        <input
          aria-label={`Answer for ${exercise.prompt}`}
          value={answer}
          maxLength={500}
          placeholder="Your answer"
          onChange={(event) => setAnswer(event.target.value)}
        />
        <button type="submit" disabled={busy || !answer.trim()}>
          Check
        </button>
        <button type="button" disabled={hintsLeft <= 0} onClick={() => void nextHint()}>
          Hint{hintsLeft > 0 ? ` (${hintsLeft} left)` : ""}
        </button>
      </form>

      {hints.map((hint) => (
        <p key={hint.hint_index} className="hint">
          Hint {hint.hint_index + 1}: {hint.hint}
        </p>
      ))}

      {verdict && result && (
        <div className={`verdict ${verdict.tone}`} role="status">
          <strong>{verdict.headline}.</strong> {result.message} <span className="muted">{verdict.provenance}</span>
          {result.feedback && <p>{result.feedback}</p>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

