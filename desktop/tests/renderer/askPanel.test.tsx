// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AskPanel } from "../../src/renderer/src/components/AskPanel";
import type { AssistantResponse } from "../../src/shared/apiTypes";

type Request = { method: string; path: string; body?: unknown };

function installBridge(respond: (request: Request) => unknown): Request[] {
  const seen: Request[] = [];
  (globalThis as unknown as { window: unknown }).window = {
    mathengine: {
      request: async (request: Request) => {
        seen.push(request);
        return respond(request) as never;
      },
    },
  };
  return seen;
}

function answer(overrides: Partial<AssistantResponse>): AssistantResponse {
  return {
    question: "multiplication facts",
    intent: "search",
    intent_reason: "A bare topic was entered; searching the library.",
    includes_drafts: false,
    status: "answer",
    library: [{ id: "arithmetic.multiplication.facts", text: "Multiplication facts are products of one-digit numbers.", sources: ["CCSS 3.OA.C.7"] }],
    next_steps: [{ id: "arithmetic.multiplication.repeated-addition", title: "Multiplication as repeated addition" }],
    qwen: { status: "unavailable", model: "test-model", error: "Ollama is not reachable." },
    ...overrides,
  };
}

function ok(body: AssistantResponse) {
  return { ok: true, status: 200, data: body };
}

async function askFor(text: string) {
  fireEvent.change(screen.getByLabelText("Question or calculation"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
}

afterEach(() => {
  cleanup();
  delete (globalThis as unknown as { window?: unknown }).window;
});

describe("AskPanel", () => {
  it("sends the question, with drafts off by default, and shows library text when the model is unavailable", async () => {
    const seen = installBridge(() => ok(answer({})));
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("multiplication facts");

    expect(await screen.findByText("Multiplication facts are products of one-digit numbers.")).toBeTruthy();
    expect(screen.getByText(/Language model unavailable/)).toBeTruthy();
    expect(screen.getByText(/Ollama is not reachable/)).toBeTruthy();
    expect(seen[0]).toEqual({
      method: "POST",
      path: "/api/assistant/ask",
      body: { question: "multiplication facts", include_drafts: false, include_diagnostics: false },
    });
  });

  it("shows a loading state while the request is running", async () => {
    let release: (value: unknown) => void = () => undefined;
    installBridge(() => new Promise((resolve) => (release = resolve)));
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("long division");
    expect(await screen.findByText(/up to two minutes/)).toBeTruthy();
    release(ok(answer({ question: "long division", qwen: { status: "not_used", reason: "No model needed." } })));
    expect(await screen.findByText("Multiplication facts are products of one-digit numbers.")).toBeTruthy();
    expect(screen.queryByText(/up to two minutes/)).toBeNull();
  });

  it("shows a visible error when the backend call fails", async () => {
    installBridge(() => ({ ok: false, status: 503, data: { detail: "Index not built" }, error: "Index not built" }));
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("fractions");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Index not built");
  });

  it("shows the explanation with its SymPy re-check when Qwen answered correctly", async () => {
    installBridge(() =>
      ok(answer({ qwen: { status: "ok", model: "test-model", text: "Seven groups of eight make 56.", guard: { allowed: true, checked_claims: 1, wrong_claims: [], undecided_claims: [] } } })),
    );
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("multiplication facts");
    expect(await screen.findByText("Seven groups of eight make 56.")).toBeTruthy();
    expect(screen.getByText(/re-checked with SymPy/)).toBeTruthy();
  });

  it("says when a model reply was withheld because its arithmetic was wrong", async () => {
    installBridge(() => ok(answer({ qwen: { status: "blocked", model: "test-model", error: "The model's reply contained arithmetic that SymPy could not confirm." } })));
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("multiplication facts");
    expect(await screen.findByText(/explanation was not shown/)).toBeTruthy();
    expect(screen.getByText("Multiplication facts are products of one-digit numbers.")).toBeTruthy();
  });

  it("shows the verified result of a calculation without calling the model", async () => {
    installBridge(() =>
      ok({
        question: "7 x 8",
        intent: "solve",
        intent_reason: "A math expression was found.",
        includes_drafts: false,
        status: "verified",
        expression: "7 * 8",
        result: "56",
        approximate: "56.0000000000",
        verified_by: "SymPy",
        qwen: { status: "not_used", reason: "Calculations are checked by SymPy." },
      }),
    );
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("7 x 8");
    expect(await screen.findByText("56")).toBeTruthy();
    expect(screen.getByText(/checked by SymPy/)).toBeTruthy();
  });

  it("asks a clarifying question and re-asks with the chosen topic", async () => {
    const seen = installBridge((request) => {
      const question = (request.body as { question: string }).question;
      if (question === "multiplication") {
        return ok({
          question,
          intent: "search",
          intent_reason: "",
          includes_drafts: false,
          status: "clarify",
          message: "Several topics match. Which one did you mean: 'Multiplication facts', 'Multiplying fractions'?",
          options: [
            { id: "arithmetic.multiplication.facts", title: "Multiplication facts", subject: "arithmetic", topic: "multiplication" },
            { id: "arithmetic.fractions.multiply", title: "Multiplying fractions", subject: "arithmetic", topic: "fractions" },
          ],
          qwen: { status: "not_used", reason: "The question is ambiguous." },
        });
      }
      return ok(answer({ question }));
    });
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("multiplication");
    fireEvent.click(await screen.findByRole("button", { name: "Multiplication facts" }));
    expect(await screen.findByText("Multiplication facts are products of one-digit numbers.")).toBeTruthy();
    expect(seen.map((request) => (request.body as { question: string }).question)).toEqual([
      "multiplication",
      "Multiplication facts",
    ]);
  });

  it("offers nearby topics when nothing relevant exists", async () => {
    installBridge(() =>
      ok({
        question: "pizza",
        intent: "search",
        intent_reason: "",
        includes_drafts: false,
        status: "not_found",
        message: "No reviewed material matches 'pizza' yet.",
        suggestions: [{ id: "arithmetic.fractions.multiply", title: "Multiplying fractions", subject: "arithmetic", topic: "fractions" }],
        qwen: { status: "not_used", reason: "No relevant record was found." },
      }),
    );
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("pizza");
    expect(await screen.findByText(/No reviewed material matches/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Multiplying fractions" })).toBeTruthy();
  });

  it("shows retrieved record IDs only in developer mode", async () => {
    installBridge(() => ok(answer({ includes_drafts: true, retrieved_ids: ["arithmetic.multiplication.facts"] })));
    render(<AskPanel includeDrafts={true} onOpen={() => undefined} />);
    await askFor("multiplication facts");
    expect(await screen.findByText(/Retrieved record IDs: arithmetic.multiplication.facts/)).toBeTruthy();
    expect(screen.getByText(/may use unreviewed AI drafts/)).toBeTruthy();
  });

  it("does not show record IDs to ordinary users", async () => {
    installBridge(() => ok(answer({ retrieved_ids: ["arithmetic.multiplication.facts"] })));
    render(<AskPanel includeDrafts={false} onOpen={() => undefined} />);
    await askFor("multiplication facts");
    await screen.findByText("Multiplication facts are products of one-digit numbers.");
    expect(screen.queryByText(/Retrieved record IDs/)).toBeNull();
  });
});
