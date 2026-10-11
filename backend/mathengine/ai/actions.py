"""Allowlisted application actions that the assistant may trigger.

Rules enforced here:
* Only actions listed in ACTIONS can run. Anything else is rejected.
* Arguments are validated against a strict schema (unknown fields and wrong types are errors).
* Handlers only call the knowledge and learning services. No filesystem, shell, database
  or code execution is reachable from an action.
* Actions never expose unreviewed drafts, exercise answers or hints beyond the requested hint.

Result format (always a dict):
  {"ok": true,  "action": name, "data": {...}}
  {"ok": false, "action": name, "error": "message"}
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import MathEngineError
from ..knowledge.models import Subject
from ..knowledge.retrieval import Retriever
from ..knowledge.store import KnowledgeStore
from ..knowledge.views import concept_summary, public_exercise
from ..learning.service import ExerciseService

CONCEPT_ID = r"^[a-z][a-z0-9_]*(\.[a-z0-9]+(?:-[a-z0-9]+)*){2,}$"
EXERCISE_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchKnowledgeArgs(_Args):
    query: str = Field(min_length=1, max_length=200)
    subject: Subject | None = None
    limit: int = Field(default=5, ge=1, le=10)


class OpenLessonArgs(_Args):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)


class StartPracticeArgs(_Args):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)
    count: int = Field(default=3, ge=1, le=10)


class ShowHintArgs(_Args):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)
    exercise_id: str = Field(pattern=EXERCISE_ID, max_length=60)
    hint_index: int = Field(default=0, ge=0, le=10)


class CheckAnswerArgs(_Args):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)
    exercise_id: str = Field(pattern=EXERCISE_ID, max_length=60)
    answer: str = Field(min_length=1, max_length=500)


class ShowRelatedArgs(_Args):
    concept_id: str = Field(pattern=CONCEPT_ID, max_length=120)


class NavigateToSubjectArgs(_Args):
    subject: Subject


class ActionError(MathEngineError):
    """The action could not be completed. The message is shown to the user."""


@dataclass(frozen=True)
class ActionContext:
    store: KnowledgeStore
    retriever: Retriever
    exercises: ExerciseService


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    args_model: type[_Args]
    handler: Callable[[ActionContext, Any], dict[str, Any]]


def _search_knowledge(ctx: ActionContext, args: SearchKnowledgeArgs) -> dict[str, Any]:
    result = ctx.retriever.search(args.query, subject=args.subject, limit=args.limit)
    return {
        "status": result.status,
        "message": result.message,
        "hits": [
            {"concept_id": hit.concept_id, "title": hit.title, "subject": hit.subject, "exact": hit.exact_match}
            for hit in result.hits
        ],
    }


def _open_lesson(ctx: ActionContext, args: OpenLessonArgs) -> dict[str, Any]:
    concept = ctx.store.get(args.concept_id)
    return {"view": "lesson", "concept": concept_summary(concept)}


def _start_practice(ctx: ActionContext, args: StartPracticeArgs) -> dict[str, Any]:
    concept = ctx.store.get(args.concept_id)
    if not concept.exercises:
        raise ActionError(f"'{concept.title}' has no practice exercises yet.")
    return {
        "view": "practice",
        "concept_id": concept.id,
        "exercises": [public_exercise(item) for item in concept.exercises[: args.count]],
    }


def _show_hint(ctx: ActionContext, args: ShowHintArgs) -> dict[str, Any]:
    outcome = ctx.exercises.hint(args.concept_id, args.exercise_id, args.hint_index)
    return {"hint_index": outcome.hint_index, "hint_count": outcome.hint_count, "hint": outcome.text}


def _check_answer(ctx: ActionContext, args: CheckAnswerArgs) -> dict[str, Any]:
    outcome = ctx.exercises.check(args.concept_id, args.exercise_id, args.answer)
    return {
        "verdict": outcome.verdict.value,
        "verified": outcome.verified,
        "method": outcome.method,
        "message": outcome.message,
        "feedback": outcome.feedback,
        "attempt_id": outcome.attempt_id,
    }


def _show_related(ctx: ActionContext, args: ShowRelatedArgs) -> dict[str, Any]:
    concept = ctx.store.get(args.concept_id)
    prerequisites = [concept_summary(ctx.store.get(item)) for item in ctx.store.direct_prerequisites(concept.id) if ctx.store.is_visible(item)]
    related = [concept_summary(ctx.store.get(item)) for item in ctx.store.direct_related(concept.id) if ctx.store.is_visible(item)]
    return {"concept_id": concept.id, "prerequisites": prerequisites, "related": related}


def _navigate_to_subject(ctx: ActionContext, args: NavigateToSubjectArgs) -> dict[str, Any]:
    concepts = ctx.store.all_concepts(subject=args.subject)
    return {"view": "subject", "subject": args.subject, "concept_ids": [item.id for item in concepts]}


ACTIONS: dict[str, ActionSpec] = {
    spec.name: spec
    for spec in (
        ActionSpec("search_knowledge", "Search reviewed concepts by title, alias, keyword or subject.", SearchKnowledgeArgs, _search_knowledge),
        ActionSpec("open_lesson", "Open the lesson for one concept.", OpenLessonArgs, _open_lesson),
        ActionSpec("start_practice", "Start practice exercises for one concept.", StartPracticeArgs, _start_practice),
        ActionSpec("show_hint", "Reveal one hint for an exercise, by index.", ShowHintArgs, _show_hint),
        ActionSpec("check_answer", "Check a student's answer with the deterministic checker.", CheckAnswerArgs, _check_answer),
        ActionSpec("show_related_concepts", "List prerequisites and related concepts.", ShowRelatedArgs, _show_related),
        ActionSpec("navigate_to_subject", "Navigate the app to one subject.", NavigateToSubjectArgs, _navigate_to_subject),
    )
}


def describe_actions() -> list[dict[str, Any]]:
    """Machine-readable catalogue of actions, including each argument schema."""
    return [
        {"name": spec.name, "description": spec.description, "arguments": spec.args_model.model_json_schema()}
        for spec in ACTIONS.values()
    ]


def execute_action(name: str, raw_args: Mapping[str, Any] | None, ctx: ActionContext) -> dict[str, Any]:
    spec = ACTIONS.get(name)
    if spec is None:
        return {"ok": False, "action": name, "error": f"Unknown action '{name}'."}
    try:
        args = spec.args_model.model_validate(dict(raw_args or {}))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in exc.errors())
        return {"ok": False, "action": name, "error": f"Invalid arguments: {problems}"}
    try:
        data = spec.handler(ctx, args)
    except MathEngineError as exc:
        return {"ok": False, "action": name, "error": str(exc)}
    return {"ok": True, "action": name, "data": data}
