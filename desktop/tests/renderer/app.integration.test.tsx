/**
 * End-to-end UI test: renders the real <App/> in jsdom and routes every call through the real
 * main-process proxy (validation included) to the Python backend.
 *
 * The backend-dependent test is skipped when nothing is listening on 127.0.0.1:8000.
 * The "backend is down" test always runs, using a closed port.
 */
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "../../src/renderer/src/App";
import { DEFAULT_BACKEND_URL, forwardRequest } from "../../src/main/backendProxy";
import type { BackendRequest } from "../../src/shared/backendRoutes";

function installBridge(backendUrl: string) {
  window.mathengine = {
    request: (request: BackendRequest) => forwardRequest(request, backendUrl),
  };
}

async function backendIsRunning(): Promise<boolean> {
  try {
    const response = await fetch(`${DEFAULT_BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(1500) });
    return response.ok;
  } catch {
    return false;
  }
}

const running = await backendIsRunning();

afterEach(() => {
  cleanup();
});

describe("App when the backend is not running", () => {
  it("explains the problem instead of failing silently", async () => {
    installBridge("http://127.0.0.1:9"); // nothing listens on port 9
    render(<App />);
    // Both the health check and the Ollama check fail, so the message is shown in both status cards.
    await waitFor(() => expect(screen.getAllByText(/not reachable at http:\/\/127\.0\.0\.1:9/).length).toBeGreaterThan(0));
  });
});

describe.skipIf(!running)("App against the running backend", () => {
  it("shows connection status and hides drafts until developer mode is turned on", async () => {
    installBridge(DEFAULT_BACKEND_URL);
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Connected/)).toBeTruthy());

    fireEvent.change(screen.getByLabelText("Search the knowledge library"), { target: { value: "times tables" } });
    fireEvent.click(screen.getByText("Search"));
    await waitFor(() => expect(screen.getByText(/unreviewed AI draft\(s\) match/)).toBeTruthy());
    expect(screen.queryByText("Multiplication facts")).toBeNull();
  });

  it("opens a draft lesson in developer mode and checks an answer with the math engine", async () => {
    installBridge(DEFAULT_BACKEND_URL);
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Connected/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/Developer mode/));
    fireEvent.change(screen.getByLabelText("Search the knowledge library"), { target: { value: "times tables" } });
    fireEvent.click(screen.getByText("Search"));
    const link = await screen.findByRole("button", { name: "Multiplication facts" });
    fireEvent.click(link);

    await screen.findByText(/Unreviewed AI draft: hidden from students by default/);
    const answer = screen.getByLabelText("Answer for What is 7 x 8?");
    fireEvent.change(answer, { target: { value: "56" } });
    const exerciseForm = answer.closest("form") as HTMLFormElement;
    fireEvent.click(within(exerciseForm).getByRole("button", { name: "Check" }));

    const verdict = await screen.findByRole("status");
    expect(verdict.textContent).toContain("Correct.");
    expect(verdict.textContent).toContain("Checked by the math engine.");
  });

  it("reports an ambiguous request and lets the user pick a concept", async () => {
    installBridge(DEFAULT_BACKEND_URL);
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Connected/)).toBeTruthy());
    fireEvent.click(screen.getByLabelText(/Developer mode/));
    fireEvent.change(screen.getByLabelText("Search the knowledge library"), { target: { value: "multiplication" } });
    fireEvent.click(screen.getByText("Search"));
    await screen.findByText(/Which one did you mean/);
    expect(screen.getByRole("button", { name: "Multiplication as repeated addition" })).toBeTruthy();
  });
});
