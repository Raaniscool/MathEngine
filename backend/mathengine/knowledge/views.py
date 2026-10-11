"""Public (frontend-safe) representations of concepts.

The frontend never receives expected answers, hints, or check specifications. Those are only
released through the exercise service, one step at a time, so a student cannot read the answer key.
"""

from __future__ import annotations

from typing import Any

from .models import Concept, Exercise
from .store import KnowledgeStore


def concept_summary(concept: Concept) -> dict[str, Any]:
    return {
        "id": concept.id,
        "title": concept.title,
        "subject": concept.subject,
        "topic": concept.topic,
        "subtopic": concept.subtopic,
        "difficulty": concept.difficulty,
        "summary": concept.summary,
        "verification_status": concept.verification.status,
        "is_draft": concept.verification.status == "ai_draft",
    }


def public_exercise(exercise: Exercise) -> dict[str, Any]:
    return {
        "id": exercise.id,
        "prompt": exercise.prompt,
        "answer_type": exercise.answer_type,
        "hint_count": len(exercise.hints),
    }


def concept_detail(concept: Concept, store: KnowledgeStore, include_drafts: bool = False) -> dict[str, Any]:
    def linked(ids: list[str]) -> list[dict[str, Any]]:
        return [
            concept_summary(store.get(item, include_drafts=include_drafts))
            for item in ids
            if store.is_visible(item, include_drafts)
        ]

    return {
        "id": concept.id,
        "schema_version": concept.schema_version,
        "title": concept.title,
        "aliases": concept.aliases,
        "subject": concept.subject,
        "topic": concept.topic,
        "subtopic": concept.subtopic,
        "difficulty": concept.difficulty,
        "keywords": concept.keywords,
        "summary": concept.summary,
        "definition": concept.definition,
        "explanations": [item.model_dump(mode="json") for item in concept.explanations],
        "formulas": [item.model_dump(mode="json") for item in concept.formulas],
        "worked_examples": [item.model_dump(mode="json") for item in concept.worked_examples],
        "misconceptions": [item.model_dump(mode="json") for item in concept.misconceptions],
        "exercises": [public_exercise(item) for item in concept.exercises],
        "prerequisites": linked(store.direct_prerequisites(concept.id)),
        "related": linked(store.direct_related(concept.id)),
        "sources": [item.model_dump(mode="json") for item in concept.sources],
        "provenance": concept.provenance.model_dump(mode="json"),
        "verification": concept.verification.model_dump(mode="json"),
        "version": concept.version,
    }
