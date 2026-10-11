"""Assistant tests with a MOCKED Ollama (httpx.MockTransport). No model or Ollama server is needed.

Real-model tests live in test_real_ollama.py and are skipped unless MATHENGINE_REAL_OLLAMA=1.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mathengine.ai.assistant import MAX_CONTEXT_CHARS, SYSTEM_PROMPT, arithmetic_claims, guard_reply
from mathengine.api.app import create_app
from mathengine.config import load_settings


class FakeOllama:
    """Records every request. `reply` is the text Qwen 'says'; `failure` simulates a transport problem."""

    def __init__(self, reply: str = "Seven groups of eight make 56.", *, failure=None, status=200, body=None):
        self.reply = reply
        self.failure = failure
        self.status = status
        self.body = body
        self.generate_calls: list[dict] = []
        self.tags_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.tags_calls += 1
            return httpx.Response(200, json={"models": [{"name": "test-model:latest"}]})
        if request.url.path == "/api/generate":
            if self.failure is not None:
                raise self.failure
            payload = json.loads(request.content)
            self.generate_calls.append(payload)
            if self.body is not None:
                return httpx.Response(self.status, json=self.body)
            if self.status >= 400:
                return httpx.Response(self.status, text="error")
            return httpx.Response(200, json={"response": self.reply, "done": True})
        return httpx.Response(404)


def _client(settings, fake: FakeOllama) -> TestClient:
    app = create_app(settings, ollama_transport=httpx.MockTransport(fake.handler))
    return TestClient(app)


def _ask(client: TestClient, question: str, **extra) -> dict:
    response = client.post("/api/assistant/ask", json={"question": question, **extra})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def fake() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def client(settings, built_index, dev_index, fake) -> TestClient:
    return _client(settings, fake)


# --- success path: Qwen gets bounded, relevant library text only ----------------------------

def test_question_with_a_match_sends_relevant_library_text_to_qwen(client, fake):
    body = _ask(client, "multiplication facts", include_drafts=True, include_diagnostics=True)

    assert body["status"] == "answer"
    assert body["retrieved_ids"][0] == "arithmetic.multiplication.facts"
    assert body["qwen"]["status"] == "ok"
    assert body["qwen"]["text"] == "Seven groups of eight make 56."
    assert len(fake.generate_calls) == 1
    sent = fake.generate_calls[0]
    assert sent["stream"] is False
    assert sent["system"] == SYSTEM_PROMPT
    assert "Multiplication facts" in sent["prompt"]  # the retrieved record's text is in the prompt
    assert "multiplication facts" in sent["prompt"].lower()


def test_prompt_is_bounded_and_never_contains_the_whole_library(client, fake):
    _ask(client, "multiplication facts", include_drafts=True)
    prompt = fake.generate_calls[0]["prompt"]
    assert len(prompt) < MAX_CONTEXT_CHARS + 1200  # library excerpt plus fixed instructions and question
    assert "Long division" not in prompt  # an unrelated record is not sent
    assert "Exponent laws" not in prompt


def test_hints_and_exercise_answers_are_not_sent_to_qwen(client, fake, store):
    _ask(client, "multiplication facts", include_drafts=True)
    prompt = fake.generate_calls[0]["prompt"]
    concept = store.get("arithmetic.multiplication.facts", include_drafts=True)
    assert concept.exercises, "the test needs a record with exercises"
    for exercise in concept.exercises:
        assert exercise.check.expected not in prompt or exercise.check.expected in concept.definition
        for hint in exercise.hints:
            assert hint not in prompt


def test_the_default_answer_uses_only_reviewed_records(client, fake):
    # Drafts are not in the default index, so Qwen never sees draft text without developer mode.
    body = _ask(client, "multiplication facts")
    assert body["includes_drafts"] is False
    assert body["status"] == "not_found"
    assert fake.generate_calls == []


# --- failure paths: the library still answers and the failure is visible --------------------

@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ConnectError("refused"), "not reachable"),
        (httpx.ReadTimeout("slow"), "did not answer within"),
    ],
)
def test_unreachable_or_slow_ollama_is_reported_and_library_text_is_still_returned(settings, built_index, dev_index, failure, expected):
    client = _client(settings, FakeOllama(failure=failure))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "unavailable"
    assert expected in body["qwen"]["error"]
    assert body["status"] == "answer"
    assert body["library"][0]["text"]  # the learner still gets the verified library text


def test_missing_model_is_reported_with_the_pull_command(settings, built_index, dev_index):
    client = _client(settings, FakeOllama(status=404))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "unavailable"
    assert "ollama pull test-model" in body["qwen"]["error"]


@pytest.mark.parametrize("body_json", [{"unexpected": True}, {"response": 42}, ["not", "an", "object"]])
def test_malformed_model_reply_is_reported_not_crashed(settings, built_index, dev_index, body_json):
    client = _client(settings, FakeOllama(body=body_json))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "unavailable"
    assert "unexpected response" in body["qwen"]["error"]


def test_empty_model_reply_is_reported(settings, built_index, dev_index):
    client = _client(settings, FakeOllama(reply="   "))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "unavailable"
    assert "empty response" in body["qwen"]["error"]


# --- the SymPy guard: Qwen cannot override arithmetic ---------------------------------------

def test_a_wrong_arithmetic_claim_from_qwen_is_blocked(settings, built_index, dev_index):
    client = _client(settings, FakeOllama(reply="Seven times eight is 7 x 8 = 54, so practise it."))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "blocked"
    assert "54" not in json.dumps(body["qwen"].get("text", ""))
    assert "text" not in body["qwen"]
    assert body["qwen"]["guard"]["wrong_claims"] == ["7 x 8 = 54"]
    assert body["library"]  # the verified library text is still shown


def test_a_correct_arithmetic_claim_passes_the_guard(settings, built_index, dev_index):
    client = _client(settings, FakeOllama(reply="Check it: 7 x 8 = 56."))
    body = _ask(client, "multiplication facts", include_drafts=True)
    assert body["qwen"]["status"] == "ok"
    assert body["qwen"]["guard"]["checked_claims"] == 1


def test_guard_checks_each_claim_with_sympy():
    assert [claim.correct for claim in arithmetic_claims("6 × 9 = 54 and 12 ÷ 4 = 3 and 2 + 2 = 5")] == [
        True,
        True,
        False,
    ]
    # A claim at the end of a sentence is still checked.
    assert [claim.correct for claim in arithmetic_claims("So 7 x 8 = 54.")] == [False]
    assert guard_reply("No arithmetic here.")["allowed"] is True
    assert guard_reply("3 - 5 = -2 is correct, 3 − 5 = 2 is not.")["allowed"] is False


# --- calculations never reach the model ------------------------------------------------------

def test_a_calculation_is_verified_by_sympy_and_qwen_is_not_called(client, fake):
    body = _ask(client, "7 x 8")
    assert body["intent"] == "solve"
    assert body["status"] == "verified"
    assert body["result"] == "56"
    assert body["verified_by"] == "SymPy"
    assert body["qwen"]["status"] == "not_used"
    assert fake.generate_calls == []


def test_an_equation_is_not_guessed_at(client, fake):
    body = _ask(client, "what is 2x + 3 = 7")
    assert body["status"] == "unsupported"
    assert fake.generate_calls == []


# --- clarification, honest not-found, and nearby suggestions ---------------------------------

def test_ambiguous_question_asks_before_calling_the_model(client, fake):
    body = _ask(client, "multiplication", include_drafts=True)
    assert body["status"] == "clarify"
    assert len(body["options"]) >= 2
    assert fake.generate_calls == []


def test_unknown_topic_is_not_guessed_and_skips_the_model(client, fake):
    body = _ask(client, "pizza", include_drafts=True)
    assert body["status"] == "not_found"
    assert body["qwen"]["status"] == "not_used"
    assert fake.generate_calls == []


def test_empty_request_asks_what_to_learn(client, fake):
    body = _ask(client, "help")
    assert body["status"] == "clarify"
    assert fake.generate_calls == []


# --- request validation ----------------------------------------------------------------------

def test_overlong_question_is_rejected_by_validation(client):
    response = client.post("/api/assistant/ask", json={"question": "x" * 501})
    assert response.status_code == 422


def test_unknown_request_fields_are_rejected(client):
    response = client.post("/api/assistant/ask", json={"question": "multiplication facts", "model": "other"})
    assert response.status_code == 422


# --- configuration changes need no code change -----------------------------------------------

def test_url_model_and_timeout_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MATHENGINE_OLLAMA_URL", "http://10.0.0.5:11434")
    monkeypatch.setenv("MATHENGINE_OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.setenv("MATHENGINE_OLLAMA_TIMEOUT", "45")
    settings = load_settings()
    assert settings.ollama_url == "http://10.0.0.5:11434"
    assert settings.ollama_model == "qwen3:4b"
    assert settings.ollama_timeout_seconds == 45.0


def test_a_bad_timeout_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("MATHENGINE_OLLAMA_TIMEOUT", "soon")
    assert load_settings().ollama_timeout_seconds == 120.0


def test_status_names_installed_qwen_models_without_switching_to_them(settings, built_index):
    # The configured model is not installed, but a Qwen model is. The message suggests it; nothing is changed.
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3:latest"}]})

    client = TestClient(create_app(settings, ollama_transport=httpx.MockTransport(handler)))
    status = client.get("/api/ollama/status").json()
    assert status["reachable"] is True
    assert status["model_installed"] is False
    assert status["model"] == "test-model"
    assert "qwen2.5:7b" in status["error"]
