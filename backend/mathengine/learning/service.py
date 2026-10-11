"""Exercise service: the single place where exercises are started, hinted and checked.

Lessons, practice, hints and the AI assistant all go through here, so every surface uses the same
answer keys and the same checking rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import BadRequestError, NotFoundError
from ..knowledge.models import Concept, Exercise
from ..knowledge.store import KnowledgeStore
from ..math.checker import Verdict, check_answer
from .progress import ProgressStore


@dataclass(frozen=True)
class CheckOutcome:
    verdict: Verdict
    verified: bool
    method: str
    message: str
    feedback: str
    attempt_id: int


@dataclass(frozen=True)
class HintOutcome:
    hint_index: int
    hint_count: int
    text: str

    @property
    def has_more(self) -> bool:
        return self.hint_index + 1 < self.hint_count


class ExerciseService:
    def __init__(self, store: KnowledgeStore, progress: ProgressStore) -> None:
        self._store = store
        self._progress = progress

    def find(self, concept_id: str, exercise_id: str, include_drafts: bool = False) -> tuple[Concept, Exercise]:
        concept = self._store.get(concept_id, include_drafts=include_drafts)
        for exercise in concept.exercises:
            if exercise.id == exercise_id:
                return concept, exercise
        raise NotFoundError(f"Concept '{concept_id}' has no exercise '{exercise_id}'.")

    def check(
        self, concept_id: str, exercise_id: str, answer: str, include_drafts: bool = False
    ) -> CheckOutcome:
        _, exercise = self.find(concept_id, exercise_id, include_drafts)
        result = check_answer(answer, exercise.check.to_spec())
        if result.verdict is Verdict.CORRECT:
            feedback = exercise.feedback_correct
        elif result.verdict is Verdict.INCORRECT:
            feedback = exercise.feedback_incorrect
        elif result.verdict is Verdict.UNVERIFIABLE:
            feedback = "This answer cannot be checked automatically yet, so no verdict is given."
        else:
            feedback = ""
        attempt_id = self._progress.record_attempt(
            concept_id, exercise_id, result.verdict.value, result.verified, result.method
        )
        return CheckOutcome(
            verdict=result.verdict,
            verified=result.verified,
            method=result.method,
            message=result.message,
            feedback=feedback,
            attempt_id=attempt_id,
        )

    def hint(self, concept_id: str, exercise_id: str, index: int, include_drafts: bool = False) -> HintOutcome:
        _, exercise = self.find(concept_id, exercise_id, include_drafts)
        if not exercise.hints:
            raise BadRequestError("This exercise has no hints.")
        if index < 0 or index >= len(exercise.hints):
            raise BadRequestError(f"Hint {index} does not exist; this exercise has {len(exercise.hints)} hint(s).")
        return HintOutcome(index, len(exercise.hints), exercise.hints[index])
