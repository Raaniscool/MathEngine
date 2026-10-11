"""Client for a local Ollama server (https://ollama.com).

Ollama is optional at this stage. When it is not running, every method returns a clear,
user-facing error instead of crashing, and the rest of the application keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..errors import MathEngineError


class OllamaUnavailableError(MathEngineError):
    """Ollama cannot be reached or the requested model is missing."""


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    model: str
    model_installed: bool
    installed_models: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


def _normalize_model_name(name: str) -> str:
    # Ollama treats "llama3" and "llama3:latest" as the same model.
    return name if ":" in name else f"{name}:latest"


class _UnexpectedResponse(Exception):
    """Ollama answered, but not with the JSON shape this client understands."""


def _installed_model_names(payload: object) -> tuple[str, ...]:
    """Read model names from a /api/tags body. Strict about the top level, tolerant of extra fields."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise _UnexpectedResponse("missing 'models' list")
    return tuple(
        item["name"] for item in payload["models"] if isinstance(item, dict) and isinstance(item.get("name"), str)
    )


def _generated_text(payload: object) -> str:
    """Read the completion from a non-streaming /api/generate body."""
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
        raise _UnexpectedResponse("missing 'response' text")
    return payload["response"]


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 3.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        self._client.close()

    def status(self) -> OllamaStatus:
        def unavailable(reason: str) -> OllamaStatus:
            return OllamaStatus(reachable=False, model=self._model, model_installed=False, error=reason)

        try:
            response = self._client.get("/api/tags")
        except (httpx.HTTPError, ValueError) as exc:
            return unavailable(
                "Ollama is not reachable. Start the Ollama app (or run `ollama serve`) "
                f"and try again. Details: {exc.__class__.__name__}"
            )
        if response.status_code >= 400:
            return unavailable(f"Ollama responded with HTTP {response.status_code} to a status check.")
        try:
            installed = _installed_model_names(response.json())
        except (ValueError, _UnexpectedResponse):
            return unavailable("Ollama responded, but not with the expected model list. Check the Ollama version.")

        wanted = _normalize_model_name(self._model)
        model_installed = any(_normalize_model_name(name) == wanted for name in installed)
        error = None if model_installed else f"Model '{self._model}' is not installed. Run: ollama pull {self._model}"
        return OllamaStatus(True, self._model, model_installed, installed, error)

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Ask the model for a completion. Raises OllamaUnavailableError with a clear message on failure."""
        payload: dict[str, object] = {"model": self._model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        try:
            response = self._client.post("/api/generate", json=payload, timeout=120.0)
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaUnavailableError("Ollama is not reachable. Start Ollama and try again.") from exc
        if response.status_code >= 400:
            raise OllamaUnavailableError(
                f"Ollama rejected the request (HTTP {response.status_code}). Is '{self._model}' installed?"
            )
        try:
            text = _generated_text(response.json())
        except (ValueError, _UnexpectedResponse) as exc:
            raise OllamaUnavailableError("Ollama returned an unexpected response. Check the Ollama version.") from exc
        if not text.strip():
            raise OllamaUnavailableError("Ollama returned an empty response. Try again or try another model.")
        return text
