"""FastAPI application factory.

Run locally with (from the backend/ folder):
    uvicorn mathengine.api.app:create_app --factory --host 127.0.0.1 --port 8000

The server binds to 127.0.0.1 on purpose: only this computer can reach it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..ai.actions import ActionContext
from ..ai.ollama import OllamaClient
from ..config import Settings, load_settings
from ..errors import BadRequestError, IndexNotBuiltError, MathEngineError, NotFoundError
from ..knowledge.retrieval import Retriever
from ..knowledge.store import KnowledgeStore
from ..learning.progress import ProgressStore
from ..learning.service import ExerciseService
from ..math.expressions import ExpressionError


@dataclass
class AppState:
    settings: Settings
    progress: ProgressStore
    ollama: OllamaClient
    store: KnowledgeStore | None = None  # authoritative: reviewed and verified records only
    store_error: str | None = None
    dev_store: KnowledgeStore | None = None  # developer preview: includes unreviewed drafts
    dev_store_error: str | None = None

    def __post_init__(self) -> None:
        self.reload_knowledge()

    def reload_knowledge(self) -> None:
        """(Re)open both indexes. Safe to call after `cli build-index`."""
        try:
            self.store = KnowledgeStore.open(self.settings.index_path)
            self.store_error = None
        except IndexNotBuiltError as exc:
            self.store = None
            self.store_error = str(exc)
        try:
            self.dev_store = KnowledgeStore.open(self.settings.dev_index_path, expect_drafts=True)
            self.dev_store_error = None
        except IndexNotBuiltError as exc:
            self.dev_store = None
            self.dev_store_error = str(exc)

    def knowledge(self, include_drafts: bool = False) -> KnowledgeStore:
        """The store to read from. Drafts come only from the developer preview index, and only on request."""
        if include_drafts:
            if self.dev_store is None:
                raise IndexNotBuiltError(self.dev_store_error or "The developer preview index is not available.")
            return self.dev_store
        if self.store is None:
            raise IndexNotBuiltError(self.store_error or "The knowledge index is not available.")
        return self.store

    def exercises(self, include_drafts: bool = False) -> ExerciseService:
        return ExerciseService(self.knowledge(include_drafts), self.progress)

    def action_context(self) -> ActionContext:
        """Assistant actions always use the authoritative index, so they can never see drafts."""
        store = self.knowledge()
        return ActionContext(store=store, retriever=Retriever(store), exercises=ExerciseService(store, self.progress))


def create_app(settings: Settings | None = None, ollama_transport=None) -> FastAPI:
    settings = settings or load_settings()
    state = AppState(
        settings=settings,
        progress=ProgressStore(settings.progress_path),
        ollama=OllamaClient(settings.ollama_url, settings.ollama_model, transport=ollama_transport),
    )

    app = FastAPI(title="MathEngine backend", version=__version__)
    app.state.mathengine = state

    @app.exception_handler(IndexNotBuiltError)
    async def _index_missing(_: Request, exc: IndexNotBuiltError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(BadRequestError)
    async def _bad_request(_: Request, exc: BadRequestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ExpressionError)
    async def _bad_expression(_: Request, exc: ExpressionError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(MathEngineError)
    async def _generic(_: Request, exc: MathEngineError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    from .routes import router  # imported here to keep module import light

    app.include_router(router)
    return app


def get_state(request: Request) -> AppState:
    return request.app.state.mathengine
