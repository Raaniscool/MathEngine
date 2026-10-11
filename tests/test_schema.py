"""Schema tests: the record format rejects malformed or dishonest records."""

from __future__ import annotations

import pytest
from helpers import record
from pydantic import ValidationError

from mathengine.knowledge.models import Concept


def _errors(data: dict) -> str:
    with pytest.raises(ValidationError) as info:
        Concept.model_validate(data)
    return str(info.value)


def test_valid_base_record_is_accepted():
    concept = Concept.model_validate(record())
    assert concept.id == "arithmetic.testing.sample"
    assert concept.verification.status == "ai_draft"


def test_unknown_field_is_rejected_instead_of_ignored():
    assert "titel" in _errors(record(titel="typo in field name"))


def test_concept_id_must_start_with_its_subject():
    assert "but subject is 'arithmetic'" in _errors(record(id="algebra.testing.sample"))


@pytest.mark.parametrize("bad_id", ["Arithmetic.Testing.Sample", "arithmetic.sample", "arithmetic..x", "arithmetic testing"])
def test_malformed_concept_ids_are_rejected(bad_id):
    assert _errors(record(id=bad_id))


def test_difficulty_must_be_between_1_and_10():
    assert _errors(record(difficulty=11))
    assert _errors(record(difficulty=0))


def test_verified_status_requires_machine_checkable_answers():
    data = record(
        verification={"status": "verified", "reviewed_by": "Reviewer", "reviewed_on": "2026-10-11"},
        exercises=[{"id": "q1", "prompt": "Explain why?", "answer_type": "expression",
                    "check": {"method": "none", "unverifiable_reason": "free text"}}],
    )
    assert "requires machine-checkable answers" in _errors(data)


def test_reviewed_status_requires_reviewer_and_date():
    assert "requires reviewed_by and reviewed_on" in _errors(record(verification={"status": "reviewed"}))


def test_ai_draft_must_not_claim_a_review():
    data = record(verification={"status": "ai_draft", "reviewed_by": "Someone", "reviewed_on": "2026-10-11"})
    assert "must not claim a review" in _errors(data)


def test_ai_generated_content_must_name_its_model():
    data = record(provenance={"origin": "ai_generated", "author": "Bot", "created": "2026-10-11"})
    assert "must name the ai_model" in _errors(data)


def test_answer_type_must_match_check_method():
    data = record(exercises=[{"id": "q1", "prompt": "Differentiate x^2 please.", "answer_type": "number",
                              "check": {"method": "derivative", "function": "x^2", "expected": "2*x"}}])
    assert "cannot use check method" in _errors(data)


def test_check_method_requires_its_fields():
    data = record(exercises=[{"id": "q1", "prompt": "Differentiate x^2 please.", "answer_type": "expression",
                              "check": {"method": "derivative", "expected": "2*x"}}])
    assert "requires: function" in _errors(data)


def test_exercise_ids_must_be_unique():
    exercise = record()["exercises"][0]
    assert "unique" in _errors(record(exercises=[exercise, dict(exercise)]))


def test_alias_may_not_repeat_the_title():
    assert "repeats the title" in _errors(record(aliases=["SAMPLE CONCEPT"]))


def test_concept_may_not_reference_itself():
    assert "cannot reference itself" in _errors(record(prerequisites=["arithmetic.testing.sample"]))


def test_formula_and_worked_example_structures_are_validated():
    assert _errors(record(worked_examples=[{"title": "Empty steps", "problem": "Something to solve here",
                                            "steps": [], "answer": "6"}]))
