"""HTTP routes. Every route validates its input with Pydantic models before touching services."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from ..ai.actions import CONCEPT_ID, EXERCISE_ID, describe_actions, execute_action
from ..knowledge.models import Subject
from ..knowledge.retrieval import Retriever
from ..knowledge.views import concept_detail, concept_summary
from ..math.evaluate import evaluate_expression
from .app import AppState, get_state

router = APIRouter(prefix="/api")
State = Annotated[AppState, Depends(get_state)]
ConceptPath = Annotated[str, Path(pattern=CONCEPT_ID, max_length=120)]
ExercisePath = Annotated[str, Path(pattern=EXERCISE_ID, max_length=60)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckRequest(_Body):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)
    exercise_id: str = Field(pattern=EXERCISE_ID, max_length=60)
    answer: str = Field(min_length=1, max_length=500)
    include_drafts: bool = False  # developer mode only: reads the preview index, which holds unreviewed drafts


class HintRequest(_Body):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)
    exercise_id: str = Field(pattern=EXERCISE_ID, max_length=60)
    index: int = Field(default=0, ge=0, le=10)
    include_drafts: bool = False


class EvaluateRequest(_Body):
    expression: str = Field(min_length=1, max_length=200)


@router.get("/health")
def health(state: State) -> dict[str, Any]:
    store = state.store
    return {
        "status": "ok",
        "app": "MathEngine",
        "version": __version__,
        "knowledge": {
            "index_built": store is not None,
            "concept_count": store.concept_count if store else 0,
            # Drafts are never in the authoritative index. This counts the ones left out of it.
            "excluded_draft_count": int(store.meta.get("excluded_draft_count", 0)) if store else 0,
            "developer_preview_built": state.dev_store is not None,
            "error": state.store_error,
        },
    }


@router.get("/ollama/status")
def ollama_status(state: State) -> dict[str, Any]:
    status = state.ollama.status()
    return {
        "reachable": status.reachable,
        "model": status.model,
        "model_installed": status.model_installed,
        "installed_models": list(status.installed_models),
        "error": status.error,
    }


@router.get("/subjects")
def subjects(state: State, include_drafts: bool = False) -> dict[str, Any]:
    store = state.knowledge(include_drafts)
    return {"subjects": [{"subject": name, "concept_count": count} for name, count in store.subject_counts(include_drafts)]}


@router.get("/concepts")
def search_concepts(
    state: State,
    q: Annotated[str, Query(min_length=0, max_length=200)] = "",
    subject: Subject | None = None,
    include_drafts: bool = False,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    store = state.knowledge(include_drafts)
    if not q.strip():
        concepts = store.all_concepts(subject=subject, include_drafts=include_drafts)
        return {"query": q, "status": "listing", "message": "", "hits": [concept_summary(c) for c in concepts]}
    result = Retriever(store).search(q, subject=subject, include_drafts=include_drafts, limit=limit)
    return {
        "query": result.query,
        "status": result.status,
        "message": result.message,
        "hits": [
            {
                "concept_id": hit.concept_id,
                "title": hit.title,
                "subject": hit.subject,
                "topic": hit.topic,
                "score": hit.score,
                "exact": hit.exact_match,
                "matched_terms": list(hit.matched_terms),
                "verification_status": hit.verification_status,
            }
            for hit in result.hits
        ],
    }


@router.get("/concepts/{concept_id}")
def get_concept(state: State, concept_id: ConceptPath, include_drafts: bool = False) -> dict[str, Any]:
    store = state.knowledge(include_drafts)
    concept = store.get(concept_id, include_drafts=include_drafts)
    return concept_detail(concept, store, include_drafts)


@router.post("/exercises/check")
def check_exercise(state: State, body: CheckRequest) -> dict[str, Any]:
    outcome = state.exercises(body.include_drafts).check(body.concept_id, body.exercise_id, body.answer, body.include_drafts)
    return {
        "verdict": outcome.verdict.value,
        "verified": outcome.verified,
        "method": outcome.method,
        "message": outcome.message,
        "feedback": outcome.feedback,
        "attempt_id": outcome.attempt_id,
    }


@router.post("/exercises/hint")
def hint_exercise(state: State, body: HintRequest) -> dict[str, Any]:
    outcome = state.exercises(body.include_drafts).hint(body.concept_id, body.exercise_id, body.index, body.include_drafts)
    return {"hint_index": outcome.hint_index, "hint_count": outcome.hint_count, "has_more": outcome.has_more, "hint": outcome.text}


@router.post("/math/evaluate")
def evaluate(body: EvaluateRequest) -> dict[str, Any]:
    result = evaluate_expression(body.expression)
    return {"exact": result.exact, "latex": result.latex, "approximate": result.approximate, "is_numeric": result.is_numeric}


@router.get("/progress/summary")
def progress_summary(state: State) -> dict[str, Any]:
    return {"concepts": state.progress.summary()}


@router.get("/actions")
def list_actions() -> dict[str, Any]:
    return {"actions": describe_actions()}


@router.post("/actions/{name}")
def run_action(
    state: State,
    name: Annotated[str, Path(max_length=64, pattern=r"^[a-z_]+$")],
    arguments: Annotated[dict[str, Any] | None, Body()] = None,
) -> JSONResponse:
    """Run one allowlisted action. Failures are returned as ok=false with HTTP 400."""
    result = execute_action(name, arguments, state.action_context())
    return JSONResponse(status_code=200 if result["ok"] else 400, content=result)


@router.post("/knowledge/reload")
def reload_knowledge(state: State) -> dict[str, Any]:
    """Re-open the index after `python -m mathengine.cli build-index`. Local-only, like the rest of the API."""
    state.reload_knowledge()
    return health(state)
