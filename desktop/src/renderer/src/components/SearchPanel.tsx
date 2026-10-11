import { useState, type FormEvent } from "react";
import type { SearchResponse } from "../../../shared/apiTypes";

const SUBJECTS = [
  "arithmetic",
  "algebra",
  "geometry",
  "trigonometry",
  "statistics",
  "calculus",
  "linear_algebra",
  "differential_equations",
  "physics",
];

interface Props {
  result: SearchResponse | null;
  busy: boolean;
  onSearch: (query: string, subject: string) => void;
  onOpen: (conceptId: string) => void;
}

export function SearchPanel({ result, busy, onSearch, onOpen }: Props) {
  const [query, setQuery] = useState("");
  const [subject, setSubject] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    onSearch(query, subject);
  }

  return (
    <section className="panel">
      <h2>Find a concept</h2>
      <form className="search-form" onSubmit={submit}>
        <input
          aria-label="Search the knowledge library"
          placeholder="e.g. times tables, power rule, solve for x"
          value={query}
          maxLength={200}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select aria-label="Subject" value={subject} onChange={(event) => setSubject(event.target.value)}>
          <option value="">All subjects</option>
          {SUBJECTS.map((item) => (
            <option key={item} value={item}>
              {item.replace("_", " ")}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          Search
        </button>
      </form>

      {result && (
        <div className={`search-result ${result.status}`}>
          <p>{result.message}</p>
          {result.hits.length > 0 && (
            <ul className="hit-list">
              {result.hits.map((hit) => (
                <li key={hit.concept_id}>
                  <button type="button" className="link" onClick={() => onOpen(hit.concept_id)}>
                    {hit.title}
                  </button>
                  <span className="muted"> · {hit.subject.replace("_", " ")} · {hit.topic}</span>
                  {hit.verification_status === "ai_draft" && <span className="badge draft">AI draft</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
