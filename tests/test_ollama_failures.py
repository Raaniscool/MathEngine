"""Ollama failure modes, tested with httpx.MockTransport. No real Ollama server is needed.

Ollama is optional and non-authoritative. Every bad response must become a clear status or a typed
OllamaUnavailableError. None may escape as an uncaught exception (which would become an HTTP 500).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from mathengine.ai.ollama import OllamaClient, OllamaUnavailableError
from mathengine.api.app import create_app


def _client(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test", "qwen2.5:1.5b", transport=httpx.MockTransport(handler))


def _respond(status: int = 200, *, text: str | None = None, json_body: object = None):
    def handler(request):
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=json_body)

    return handler


def _raise(exc: Exception):
    def handler(request):
        raise exc

    return handler


# --- status(): /api/tags -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        ["not", "an", "object"],  # JSON array at the top level
        "just a string",
        42,
        None,
        {"models": "not-a-list"},
        {"models": None},
        {"something_else": []},
    ],
)
def test_status_rejects_wrong_top_level_shapes(body):
    status = _client(_respond(json_body=body)).status()
    assert status.reachable is False
    assert "expected model list" in status.error


def test_status_rejects_non_json_body():
    status = _client(_respond(text="<html>proxy error</html>")).status()
    assert status.reachable is False
    assert "expected model list" in status.error


def test_status_skips_malformed_model_entries_but_still_finds_the_model():
    body = {"models": [None, 7, {"name": None}, {"no_name": True}, {"name": "qwen2.5:1.5b"}, "x"]}
    status = _client(_respond(json_body=body)).status()
    assert status.reachable is True
    assert status.installed_models == ("qwen2.5:1.5b",)
    assert status.model_installed is True


def test_status_treats_missing_tag_as_latest():
    # Ollama stores "llama3" as "llama3:latest", so a bare name must match its ":latest" entry.
    bare = OllamaClient("http://ollama.test", "llama3", transport=httpx.MockTransport(_respond(json_body={"models": [{"name": "llama3:latest"}]})))
    assert bare.status().model_installed is True
    other = OllamaClient("http://ollama.test", "qwen2.5", transport=httpx.MockTransport(_respond(json_body={"models": [{"name": "qwen2.5:1.5b"}]})))
    assert other.status().model_installed is False


def test_status_reports_http_error_as_responded_not_unreachable():
    status = _client(_respond(500, json_body={"error": "boom"})).status()
    assert status.reachable is False
    assert "HTTP 500" in status.error
    assert "not reachable" not in status.error


def test_status_reports_404_on_tags_endpoint():
    status = _client(_respond(404, json_body={"error": "not found"})).status()
    assert status.reachable is False
    assert "HTTP 404" in status.error


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow connect"),
        httpx.RemoteProtocolError("dropped"),
    ],
)
def test_status_reports_transport_failures_as_unreachable(exc):
    status = _client(_raise(exc)).status()
    assert status.reachable is False
    assert "Ollama is not reachable" in status.error
    assert type(exc).__name__ in status.error


def test_status_model_check_is_exact_not_substring():
    status = _client(_respond(json_body={"models": [{"name": "qwen2.5:1.5b-instruct"}]})).status()
    assert status.model_installed is False


# --- generate(): /api/generate ----------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        ["response", "as", "a", "list"],
        "a bare string",
        {"response": None},
        {"response": 42},
        {"text": "wrong key"},
        {},
    ],
)
def test_generate_rejects_wrong_shapes(body):
    with pytest.raises(OllamaUnavailableError, match="unexpected response"):
        _client(_respond(json_body=body)).generate("2 x 3?")


def test_generate_rejects_non_json_body():
    with pytest.raises(OllamaUnavailableError, match="unexpected response"):
        _client(_respond(text="not json at all")).generate("2 x 3?")


def test_generate_rejects_empty_or_whitespace_text():
    for text in ("", "   \n"):
        with pytest.raises(OllamaUnavailableError, match="empty response"):
            _client(_respond(json_body={"response": text, "done": True})).generate("2 x 3?")


def test_generate_404_for_missing_model_gives_pull_hint():
    handler = _respond(404, json_body={"error": "model 'qwen2.5:1.5b' not found"})
    with pytest.raises(OllamaUnavailableError, match="HTTP 404.*Is 'qwen2.5:1.5b' installed"):
        _client(handler).generate("hello")


def test_generate_500_is_a_clear_error_not_a_crash():
    with pytest.raises(OllamaUnavailableError, match="HTTP 500"):
        _client(_respond(500, json_body={"error": "out of memory"})).generate("hello")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
def test_generate_timeouts_and_connection_errors_are_typed(exc):
    with pytest.raises(OllamaUnavailableError, match="not reachable"):
        _client(_raise(exc)).generate("hello")


def test_generate_returns_text_from_a_valid_body():
    assert _client(_respond(json_body={"model": "m", "response": "6", "done": True})).generate("2x3") == "6"


def test_generate_sends_non_streaming_request_with_system_prompt():
    seen = {}

    def handler(request):
        seen["body"] = request.read()
        return httpx.Response(200, json={"response": "ok"})

    _client(handler).generate("prompt text", system="be brief")
    assert b'"stream":false' in seen["body"].replace(b" ", b"")
    assert b"be brief" in seen["body"]


# --- The rest of the API keeps working when Ollama is down ------------------------------------


def test_non_ai_endpoints_work_when_ollama_is_down(settings, built_index, dev_index):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    client = TestClient(create_app(settings, ollama_transport=httpx.MockTransport(refuse)))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/subjects").status_code == 200
    assert client.get("/api/concepts").status_code == 200
    assert client.post("/api/math/evaluate", json={"expression": "2*3"}).status_code == 200
    status = client.get("/api/ollama/status")
    assert status.status_code == 200
    assert status.json()["reachable"] is False


def test_ollama_status_endpoint_survives_malformed_ollama_response(settings, built_index):
    def handler(request):
        return httpx.Response(200, json=["not", "the", "right", "shape"])

    response = TestClient(create_app(settings, ollama_transport=httpx.MockTransport(handler))).get("/api/ollama/status")
    assert response.status_code == 200
    assert response.json()["reachable"] is False
