import type { HealthResponse, OllamaStatusResponse } from "../../../shared/apiTypes";

interface Props {
  health: HealthResponse | null;
  healthError: string | null;
  ollama: OllamaStatusResponse | null;
  ollamaError: string | null;
}

export function StatusBar({ health, healthError, ollama, ollamaError }: Props) {
  return (
    <section className="status-bar" aria-label="System status">
      <div className={`status-item ${health ? "ok" : healthError ? "bad" : "pending"}`}>
        <strong>Backend</strong>
        {health ? (
          <span>
            Connected · v{health.version}
            {health.knowledge.index_built
              ? ` · ${health.knowledge.concept_count} published, ${health.knowledge.draft_count} draft`
              : " · knowledge index not built"}
          </span>
        ) : (
          <span>{healthError ?? "Checking…"}</span>
        )}
      </div>
      <div className={`status-item ${ollama?.reachable && ollama.model_installed ? "ok" : ollama ? "warn" : "pending"}`}>
        <strong>Ollama</strong>
        {ollama ? (
          ollama.reachable && ollama.model_installed ? (
            <span>Running · model {ollama.model}</span>
          ) : (
            <span>{ollama.error ?? "Not ready"}</span>
          )
        ) : (
          <span>{ollamaError ?? "Checking…"}</span>
        )}
      </div>
    </section>
  );
}
