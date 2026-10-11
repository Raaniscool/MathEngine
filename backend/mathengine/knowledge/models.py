"""Schema for knowledge records: the authoritative, version-controlled source format.

One concept per YAML file, stored in knowledge/<subject>/. Every model uses extra="forbid",
so a misspelled field name is reported as an error instead of being silently ignored.

Trust levels (field verification.status):
  ai_draft  - written or proposed by AI, NOT reviewed by a human. Hidden from normal retrieval.
  reviewed  - checked by a human reviewer. Exercise answers are still machine-checked on every build.
  verified  - reviewed AND every exercise has a machine-checkable answer (no 'none' checks).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..math.checker import CheckSpec

SCHEMA_VERSION = 1

Subject = Literal[
    "arithmetic",
    "algebra",
    "geometry",
    "trigonometry",
    "statistics",
    "calculus",
    "linear_algebra",
    "differential_equations",
    "physics",
]
SUBJECTS: tuple[str, ...] = get_args(Subject)

# Example: "arithmetic.multiplication.facts". The first segment must equal the subject.
CONCEPT_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9]+(?:-[a-z0-9]+)*){2,}$"
EXERCISE_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
_CONCEPT_ID_RE = re.compile(CONCEPT_ID_PATTERN)

ExplanationLevel = Literal["intro", "standard", "advanced"]
CheckMethod = Literal["exact_numeric", "symbolic_equivalence", "derivative", "solve_equation", "none"]
AnswerType = Literal["number", "expression", "equation_solution"]
VerificationStatus = Literal["ai_draft", "reviewed", "verified"]
SourceKind = Literal["textbook", "curriculum", "standard", "website", "internal"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Variable(_Strict):
    symbol: str = Field(min_length=1, max_length=8)
    meaning: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=40)


class Formula(_Strict):
    name: str = Field(min_length=1, max_length=120)
    expression: str = Field(min_length=1, max_length=300)
    # Optional. If given, the loader proves that expression == result (the law is checked, not trusted).
    result: str | None = Field(default=None, max_length=300)
    variables: list[Variable] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class Explanation(_Strict):
    level: ExplanationLevel
    text: str = Field(min_length=10, max_length=4000)


class WorkedExample(_Strict):
    title: str = Field(min_length=3, max_length=120)
    problem: str = Field(min_length=5, max_length=1000)
    steps: list[str] = Field(min_length=1, max_length=20)
    answer: str = Field(min_length=1, max_length=300)


class Misconception(_Strict):
    description: str = Field(min_length=5, max_length=500)
    explanation: str = Field(min_length=5, max_length=1000)
    correction: str = Field(min_length=5, max_length=1000)


class SourceRef(_Strict):
    title: str = Field(min_length=3, max_length=250)
    kind: SourceKind
    url: str | None = Field(default=None, pattern=r"^https://\S+$", max_length=500)


class Provenance(_Strict):
    origin: Literal["human_authored", "ai_generated"]
    author: str = Field(min_length=2, max_length=120)
    created: date
    ai_model: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _ai_fields(self) -> Provenance:
        if self.origin == "ai_generated" and not self.ai_model:
            raise ValueError("ai_generated content must name the ai_model that produced it")
        if self.origin == "human_authored" and self.ai_model:
            raise ValueError("ai_model should only be set for ai_generated content")
        return self


class Verification(_Strict):
    status: VerificationStatus
    reviewed_by: str | None = Field(default=None, max_length=120)
    reviewed_on: date | None = None
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _review_fields(self) -> Verification:
        reviewed = self.status in ("reviewed", "verified")
        if reviewed and (not self.reviewed_by or self.reviewed_on is None):
            raise ValueError(f"status '{self.status}' requires reviewed_by and reviewed_on")
        if not reviewed and (self.reviewed_by or self.reviewed_on is not None):
            raise ValueError("ai_draft records must not claim a review (remove reviewed_by/reviewed_on)")
        return self


class AnswerCheck(_Strict):
    method: CheckMethod
    expected: str | None = Field(default=None, max_length=300)
    function: str | None = Field(default=None, max_length=300)
    variable: str = Field(default="x", pattern=r"^[a-zA-Z]$")
    equation: str | None = Field(default=None, max_length=300)
    unverifiable_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _fields_for_method(self) -> AnswerCheck:
        required_by_method: dict[str, tuple[str, ...]] = {
            "exact_numeric": ("expected",),
            "symbolic_equivalence": ("expected",),
            "derivative": ("function", "expected"),
            "solve_equation": ("equation", "expected"),
            "none": ("unverifiable_reason",),
        }
        missing = [name for name in required_by_method[self.method] if not getattr(self, name)]
        if missing:
            raise ValueError(f"check method '{self.method}' requires: {', '.join(missing)}")
        return self

    def to_spec(self) -> CheckSpec:
        return CheckSpec(
            method=self.method,
            expected=self.expected,
            function=self.function,
            variable=self.variable,
            equation=self.equation,
            unverifiable_reason=self.unverifiable_reason,
        )


_ANSWER_TYPE_FOR_METHOD: dict[str, tuple[str, ...]] = {
    "number": ("exact_numeric", "none"),
    "expression": ("symbolic_equivalence", "derivative", "none"),
    "equation_solution": ("solve_equation", "none"),
}


class Exercise(_Strict):
    id: str = Field(pattern=EXERCISE_ID_PATTERN, max_length=60)
    prompt: str = Field(min_length=10, max_length=1000)
    answer_type: AnswerType
    check: AnswerCheck
    hints: list[str] = Field(default_factory=list, max_length=5)
    feedback_correct: str = Field(default="Correct.", max_length=500)
    feedback_incorrect: str = Field(default="Not quite. Check each step and try again.", max_length=500)

    @model_validator(mode="after")
    def _answer_type_matches_method(self) -> Exercise:
        allowed = _ANSWER_TYPE_FOR_METHOD[self.answer_type]
        if self.check.method not in allowed:
            raise ValueError(
                f"answer_type '{self.answer_type}' cannot use check method '{self.check.method}'"
            )
        return self


class Concept(_Strict):
    schema_version: Literal[1]
    id: str = Field(pattern=CONCEPT_ID_PATTERN, max_length=120)
    title: str = Field(min_length=3, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    subject: Subject
    topic: str = Field(min_length=2, max_length=60)
    subtopic: str | None = Field(default=None, max_length=60)
    difficulty: int = Field(ge=1, le=10)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    summary: str = Field(min_length=10, max_length=300)
    definition: str = Field(min_length=10, max_length=3000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    related: list[str] = Field(default_factory=list, max_length=30)
    explanations: list[Explanation] = Field(min_length=1)
    formulas: list[Formula] = Field(default_factory=list, max_length=20)
    worked_examples: list[WorkedExample] = Field(default_factory=list, max_length=10)
    exercises: list[Exercise] = Field(default_factory=list, max_length=50)
    misconceptions: list[Misconception] = Field(default_factory=list, max_length=20)
    sources: list[SourceRef] = Field(min_length=1)
    provenance: Provenance
    verification: Verification
    version: str = Field(pattern=VERSION_PATTERN)

    @field_validator("prerequisites", "related")
    @classmethod
    def _references_well_formed(cls, value: list[str]) -> list[str]:
        for reference in value:
            if not _CONCEPT_ID_RE.match(reference):
                raise ValueError(f"'{reference}' is not a valid concept id")
        if len(set(value)) != len(value):
            raise ValueError("the list contains duplicate concept ids")
        return value

    @field_validator("aliases", "keywords")
    @classmethod
    def _unique_entries(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for entry in value:
            key = entry.strip().lower()
            if not key:
                raise ValueError("empty entries are not allowed")
            if key in seen:
                raise ValueError(f"duplicate entry {entry!r} (comparison ignores case)")
            seen.add(key)
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> Concept:
        id_subject = self.id.split(".")[0]
        if id_subject != self.subject:
            raise ValueError(f"the id starts with '{id_subject}' but subject is '{self.subject}'")
        if self.id in self.prerequisites or self.id in self.related:
            raise ValueError("a concept cannot reference itself")
        if self.title.lower() in {alias.lower() for alias in self.aliases}:
            raise ValueError("an alias repeats the title")
        exercise_ids = [exercise.id for exercise in self.exercises]
        if len(set(exercise_ids)) != len(exercise_ids):
            raise ValueError("exercise ids must be unique within a concept")
        if self.verification.status == "verified":
            unchecked = [exercise.id for exercise in self.exercises if exercise.check.method == "none"]
            if unchecked:
                raise ValueError(
                    f"status 'verified' requires machine-checkable answers; unchecked: {unchecked}"
                )
        return self
