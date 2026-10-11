"""REAL-MODEL tests. They call the Ollama server and model configured in MATHENGINE_OLLAMA_URL / _MODEL.

Skipped by default. Run them on a machine with Ollama running and the model pulled:
    set MATHENGINE_REAL_OLLAMA=1            (PowerShell: $env:MATHENGINE_REAL_OLLAMA="1")
    pytest -q -m real_ollama
They check that the real model can be reached and that its answers pass the same guard as the mocked tests.
They do not assume a model name: they use whatever MATHENGINE_OLLAMA_MODEL is set to.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from mathengine.ai.ollama import OllamaClient
from mathengine.api.app import create_app
from mathengine.config import load_settings

pytestmark = pytest.mark.real_ollama

if os.environ.get("MATHENGINE_REAL_OLLAMA") != "1":
    pytest.skip("real-model tests: set MATHENGINE_REAL_OLLAMA=1 to run them", allow_module_level=True)


@pytest.fixture(scope="module")
def real_settings(tmp_path_factory):
    settings = load_settings()
    return settings


@pytest.fixture(scope="module")
def real_client(real_settings, tmp_path_factory):
    # Use the repository's built indexes. Run `build-index` first.
    return TestClient(create_app(real_settings))


def test_the_configured_model_is_reachable_and_installed(real_client):
    status = real_client.get("/api/ollama/status").json()
    assert status["reachable"] is True, status["error"]
    assert status["model_installed"] is True, status["error"]


def test_a_library_question_gets_a_guarded_model_answer(real_client):
    body = real_client.post(
        "/api/assistant/ask",
        json={"question": "multiplication facts", "include_drafts": True, "include_diagnostics": True},
    ).json()
    assert body["status"] == "answer"
    assert body["qwen"]["status"] in ("ok", "blocked"), body["qwen"]
    if body["qwen"]["status"] == "ok":
        assert body["qwen"]["text"].strip()


def test_arithmetic_is_still_decided_by_sympy_with_a_real_model(real_client):
    body = real_client.post("/api/assistant/ask", json={"question": "7 x 8"}).json()
    assert body["result"] == "56"
    assert body["qwen"]["status"] == "not_used"


def test_real_client_reports_a_clear_error_for_a_wrong_model_name(real_settings):
    client = OllamaClient(real_settings.ollama_url, "no-such-model-for-mathengine-tests", timeout=5)
    status = client.status()
    assert status.model_installed is False
    assert status.error
