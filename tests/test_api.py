"""HTTP API tests (in-process, via FastAPI's TestClient). They check status codes and what leaves the server."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import write_yaml

from mathengine.api.app import create_app
from mathengine.config import Settings
from mathengine.knowledge.index import build_index
from mathengine.knowledge.loader import load_knowledge

from helpers import PUBLISHED_ANSWER, PUBLISHED_ID, published_record

FACTS = "arithmetic.multiplication.facts"
POWER_RULE = "calculus.derivatives.power-rule"


def _app(settings: Settings, handler=None):
    transport = httpx.MockTransport(handler) if handler else None
    return create_app(settings, ollama_transport=transport)


@pytest.fixture
def client(settings, built_index) -> TestClient:
    """Real knowledge library (all drafts) with the index built."""
    return TestClient(_app(settings))


@pytest.fixture
def published_client(tmp_path, settings) -> TestClient:
    """Settings whose index contains one reviewed concept with a known answer key."""
    library = tmp_path / "library"
    write_yaml(library, "arithmetic/published.yaml", published_record())
    report = load_knowledge(library)
    assert report.ok, [str(issue) for issue in report.errors]
    build_index(report, settings.index_path)
    return TestClient(_app(settings))


def test_health_reports_index_state(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["knowledge"]["index_built"] is True
    assert body["knowledge"]["draft_count"] == 5
    assert body["knowledge"]["concept_count"] == 0


def test_health_still_works_without_an_index(settings):
    body = TestClient(_app(settings)).get("/api/health").json()
    assert body["status"] == "ok"
    assert body["knowledge"]["index_built"] is False
    assert "build-index" in body["knowledge"]["error"]


def test_knowledge_endpoints_return_503_with_instructions_when_index_is_missing(settings):
    response = TestClient(_app(settings)).get("/api/subjects")
    assert response.status_code == 503
    assert "build-index" in response.json()["detail"]


def test_draft_concepts_are_hidden_from_the_default_api(client):
    assert client.get(f"/api/concepts/{POWER_RULE}").status_code == 404
    assert client.get("/api/concepts?q=power+rule").json()["status"] == "insufficient"


def test_draft_concepts_are_visible_only_when_explicitly_requested(client):
    response = client.get(f"/api/concepts/{POWER_RULE}?include_drafts=true")
    assert response.status_code == 200
    assert response.json()["verification"]["status"] == "ai_draft"
    search = client.get("/api/concepts?q=multiplication&include_drafts=true").json()
    assert search["status"] == "ambiguous"


def test_concept_detail_never_contains_answer_keys(client):
    body = client.get(f"/api/concepts/{FACTS}?include_drafts=true").json()
    text = str(body)
    assert "expected" not in text
    assert "'check'" not in text
    assert body["exercises"][0].keys() == {"id", "prompt", "answer_type", "hint_count"}
    assert "56" not in [str(exercise.get("expected")) for exercise in body["exercises"]]


def test_unknown_concept_and_bad_id_format_are_handled(client):
    assert client.get("/api/concepts/arithmetic.nope.nothing").status_code == 404
    assert client.get("/api/concepts/NOT_AN_ID").status_code == 422


def test_correct_answer_is_checked_and_recorded(published_client):
    response = published_client.post(
        "/api/exercises/check",
        json={"concept_id": PUBLISHED_ID, "exercise_id": "secret-product", "answer": PUBLISHED_ANSWER},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["verdict"] == "correct"
    assert body["verified"] is True
    assert body["feedback"] == "Correct feedback."
    summary = published_client.get("/api/progress/summary").json()
    assert summary["concepts"][PUBLISHED_ID] == {"attempts": 1, "correct": 1}


def test_check_request_rejects_unexpected_fields(published_client):
    response = published_client.post(
        "/api/exercises/check",
        json={"concept_id": PUBLISHED_ID, "exercise_id": "secret-product", "answer": "1", "expected": "x"},
    )
    assert response.status_code == 422


def test_hints_are_released_one_at_a_time(published_client):
    first = published_client.post("/api/exercises/hint", json={"concept_id": PUBLISHED_ID, "exercise_id": "secret-product", "index": 0}).json()
    assert first["hint"] == "HINT-ZERO-TEXT"
    assert first["has_more"] is True
    out_of_range = published_client.post("/api/exercises/hint", json={"concept_id": PUBLISHED_ID, "exercise_id": "secret-product", "index": 7})
    assert out_of_range.status_code == 400


def test_math_endpoint_evaluates_exactly(client):
    body = client.post("/api/math/evaluate", json={"expression": "2^3 + 1/2"}).json()
    assert body["exact"] == "17/2"
    assert body["is_numeric"] is True


@pytest.mark.parametrize("expression", ['__import__("os")', "1/0", "x = 2"])
def test_math_endpoint_refuses_unsafe_or_invalid_input(client, expression):
    response = client.post("/api/math/evaluate", json={"expression": expression})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_action_endpoint_runs_allowlisted_actions_only(published_client):
    ok = published_client.post("/api/actions/search_knowledge", json={"query": "published alias"})
    assert ok.status_code == 200
    assert ok.json()["data"]["status"] == "matches"

    unknown = published_client.post("/api/actions/delete_database", json={})
    assert unknown.status_code == 400
    assert unknown.json()["ok"] is False


def test_action_endpoint_rejects_unknown_argument_names(published_client):
    response = published_client.post("/api/actions/show_hint", json={"concept_id": PUBLISHED_ID, "exercise_id": "secret-product", "path": "/etc"})
    assert response.status_code == 400


def test_ollama_status_when_ollama_is_not_running(settings, built_index):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    body = TestClient(_app(settings, refuse)).get("/api/ollama/status").json()
    assert body["reachable"] is False
    assert "Ollama is not reachable" in body["error"]


def test_ollama_status_when_model_is_installed(settings, built_index):
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "test-model:latest"}]})

    body = TestClient(_app(settings, handler)).get("/api/ollama/status").json()
    assert body["reachable"] is True
    assert body["model_installed"] is True


def test_reload_picks_up_a_newly_built_index(settings):
    client = TestClient(_app(settings))
    assert client.get("/api/health").json()["knowledge"]["index_built"] is False
    library = settings.knowledge_dir
    build_index(load_knowledge(library), settings.index_path)
    assert client.post("/api/knowledge/reload").json()["knowledge"]["index_built"] is True


def test_draft_exercises_can_be_checked_only_when_explicitly_requested(client):
    hidden = client.post(
        "/api/exercises/check",
        json={"concept_id": FACTS, "exercise_id": "seven-times-eight", "answer": "56"},
    )
    assert hidden.status_code == 404
    shown = client.post(
        "/api/exercises/check",
        json={"concept_id": FACTS, "exercise_id": "seven-times-eight", "answer": "56", "include_drafts": True},
    )
    assert shown.status_code == 200
    assert shown.json()["verdict"] == "correct"
