import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusBar } from "../../src/renderer/src/components/StatusBar";
import type { ConceptDetail } from "../../src/shared/apiTypes";
import { ConceptView } from "../../src/renderer/src/components/ConceptView";

describe("StatusBar", () => {
  it("explains a backend that is not running", () => {
    const html = renderToStaticMarkup(
      <StatusBar health={null} healthError="The MathEngine backend is not reachable" ollama={null} ollamaError={null} />,
    );
    expect(html).toContain("The MathEngine backend is not reachable");
  });

  it("shows Ollama's missing-model advice", () => {
    const html = renderToStaticMarkup(
      <StatusBar
        health={{ status: "ok", app: "MathEngine", version: "0.1.0", knowledge: { index_built: true, concept_count: 3, draft_count: 0, error: null } }}
        healthError={null}
        ollama={{ reachable: true, model: "qwen2.5:1.5b", model_installed: false, installed_models: [], error: "Model 'qwen2.5:1.5b' is not installed. Run: ollama pull qwen2.5:1.5b" }}
        ollamaError={null}
      />,
    );
    expect(html).toContain("ollama pull qwen2.5:1.5b");
    expect(html).toContain("3 published, 0 draft");
  });
});

const detail: ConceptDetail = {
  id: "calculus.derivatives.power-rule",
  title: "Power rule for derivatives",
  aliases: [],
  subject: "calculus",
  topic: "derivatives",
  subtopic: "rules",
  difficulty: 5,
  summary: "If f(x) = x^n then f'(x) = n x^(n-1).",
  definition: "The derivative of x^n is n x^(n-1).",
  explanations: [{ level: "intro", text: "A derivative is a rate of change." }],
  formulas: [],
  worked_examples: [],
  misconceptions: [],
  exercises: [{ id: "power-of-five", prompt: "Differentiate f(x) = x^5.", answer_type: "expression", hint_count: 2 }],
  prerequisites: [],
  related: [],
  sources: [{ title: "Calculus textbook", kind: "textbook", url: null }],
  verification: { status: "ai_draft", reviewed_by: null, reviewed_on: null, notes: "" },
  version: "0.1.0",
};

describe("ConceptView", () => {
  it("labels unreviewed AI drafts clearly", () => {
    const html = renderToStaticMarkup(<ConceptView concept={detail} includeDrafts onOpen={() => undefined} />);
    expect(html).toContain("Unreviewed AI draft");
    expect(html).toContain("AI-generated, not yet reviewed");
  });

  it("shows exercise prompts but never answer keys", () => {
    const html = renderToStaticMarkup(<ConceptView concept={detail} includeDrafts onOpen={() => undefined} />);
    expect(html).toContain("Differentiate f(x) = x^5.");
    expect(html).not.toMatch(/expected|5\*x\^4|5x\^4/);
  });
});
