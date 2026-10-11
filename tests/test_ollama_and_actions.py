"""Ollama client errors and the allowlisted action registry."""

from __future__ import annotations

import httpx
import pytest

from mathengine.ai.actions import ACTIONS, ActionContext, describe_actions, execute_action
from mathengine.ai.ollama import OllamaClient, OllamaUnavailableError
from mathengine.knowledge.retrieval import Retriever
from mathengine.learning.progress import ProgressStore
from mathengine.learning.service import ExerciseService

FACTS = "arithmetic.multiplication.facts"


def _client(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test", "qwen2.5:1.5b", transport=httpx.MockTransport(handler))


def test_status_reports_unreachable_ollama_clearly():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    status = _client(refuse).status()
    assert status.reachable is False
    assert "Ollama is not reachable" in status.error


def test_status_reports_missing_model_with_pull_hint():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})

    status = _client(handler).status()
    assert status.reachable is True
    assert status.model_installed is False
    assert "ollama pull qwen2.5:1.5b" in status.error


def test_status_accepts_installed_model():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})

    status = _client(handler).status()
    assert status.model_installed is True
    assert status.error is None


def test_generate_raises_clear_error_when_unavailable():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(OllamaUnavailableError, match="not reachable"):
        _client(refuse).generate("hello")


def test_generate_returns_model_text():
    def handler(request):
        assert b'"stream":false' in request.content.replace(b" ", b"")
        return httpx.Response(200, json={"response": "Hi there"})

    assert _client(handler).generate("hello") == "Hi there"


@pytest.fixture
def ctx(published_store, data_dir) -> ActionContext:
    progress = ProgressStore(data_dir / "user" / "progress.sqlite")
    return ActionContext(
        store=published_store, retriever=Retriever(published_store), exercises=ExerciseService(published_store, progress)
    )


PUBLISHED = "arithmetic.testing.published"


def test_registry_contains_exactly_the_approved_actions():
    assert set(ACTIONS) == {
        "search_knowledge",
        "open_lesson",
        "start_practice",
        "show_hint",
        "check_answer",
        "show_related_concepts",
        "navigate_to_subject",
    }
    assert {item["name"] for item in describe_actions()} == set(ACTIONS)


def test_each_action_publishes_a_json_schema_for_its_arguments():
    for item in describe_actions():
        assert item["arguments"]["type"] == "object"
        assert item["arguments"].get("additionalProperties") is False


def test_unknown_action_is_rejected(ctx):
    result = execute_action("run_shell", {"command": "rm -rf /"}, ctx)
    assert result == {"ok": False, "action": "run_shell", "error": "Unknown action 'run_shell'."}


def test_unexpected_arguments_are_rejected(ctx):
    result = execute_action("search_knowledge", {"query": "published", "filesystem": "/"}, ctx)
    assert result["ok"] is False
    assert "filesystem" in result["error"]


def test_wrong_argument_types_and_ranges_are_rejected(ctx):
    assert execute_action("search_knowledge", {"query": "published", "limit": 1000}, ctx)["ok"] is False
    assert execute_action("check_answer", {"concept_id": "not a valid id", "exercise_id": "x", "answer": "1"}, ctx)["ok"] is False
    assert execute_action("navigate_to_subject", {"subject": "cooking"}, ctx)["ok"] is False


def test_search_action_returns_structured_results(ctx):
    result = execute_action("search_knowledge", {"query": "published alias"}, ctx)
    assert result["ok"] is True
    assert result["data"]["status"] == "matches"
    assert result["data"]["hits"][0]["concept_id"] == PUBLISHED


def test_start_practice_returns_questions_without_answer_keys(ctx):
    result = execute_action("start_practice", {"concept_id": PUBLISHED, "count": 2}, ctx)
    assert result["ok"] is True
    assert "424242" not in str(result["data"])
    assert result["data"]["exercises"][0]["id"] == "secret-product"


def test_show_hint_reveals_hints_in_order(ctx):
    first = execute_action("show_hint", {"concept_id": PUBLISHED, "exercise_id": "secret-product"}, ctx)
    second = execute_action("show_hint", {"concept_id": PUBLISHED, "exercise_id": "secret-product", "hint_index": 1}, ctx)
    assert first["data"]["hint"] == "HINT-ZERO-TEXT"
    assert second["data"]["hint"] == "HINT-ONE-TEXT"


def test_check_action_grades_and_records_the_attempt(ctx):
    right = execute_action("check_answer", {"concept_id": PUBLISHED, "exercise_id": "secret-product", "answer": "42 * 10000 + 4242"}, ctx)
    wrong = execute_action("check_answer", {"concept_id": PUBLISHED, "exercise_id": "secret-product", "answer": "41"}, ctx)
    assert right["data"]["verdict"] == "correct"
    assert right["data"]["verified"] is True
    assert wrong["data"]["verdict"] == "incorrect"
    assert wrong["data"]["attempt_id"] > right["data"]["attempt_id"]


def test_navigation_actions_return_view_intents(ctx):
    lesson = execute_action("open_lesson", {"concept_id": PUBLISHED}, ctx)
    subject = execute_action("navigate_to_subject", {"subject": "arithmetic"}, ctx)
    assert lesson["data"]["view"] == "lesson"
    assert subject["data"]["view"] == "subject"
    assert PUBLISHED in subject["data"]["concept_ids"]


def test_actions_cannot_reach_drafts(authoritative_store, data_dir):
    """The assistant runs on the authoritative index, which contains no drafts at all."""
    progress = ProgressStore(data_dir / "user" / "progress.sqlite")
    ctx = ActionContext(
        store=authoritative_store,
        retriever=Retriever(authoritative_store),
        exercises=ExerciseService(authoritative_store, progress),
    )
    result = execute_action("open_lesson", {"concept_id": "calculus.derivatives.power-rule"}, ctx)
    assert result["ok"] is False
    assert "calculus.derivatives.power-rule" in result["error"]
    search = execute_action("search_concepts", {"query": "power rule"}, ctx)
    assert "draft" not in str(search).lower()
