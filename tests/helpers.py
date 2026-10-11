"""Helpers for building valid and deliberately invalid knowledge records in tests."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PUBLISHED_ID = "arithmetic.testing.published"
PUBLISHED_ANSWER = "424242"

BASE_RECORD: dict[str, Any] = {
    "schema_version": 1,
    "id": "arithmetic.testing.sample",
    "title": "Sample concept",
    "aliases": ["sample alias"],
    "keywords": ["sample keyword"],
    "subject": "arithmetic",
    "topic": "testing",
    "difficulty": 2,
    "summary": "A short summary used only by the test suite.",
    "definition": "A longer definition used only by the test suite for validation.",
    "explanations": [{"level": "intro", "text": "An intro explanation used only in tests."}],
    "exercises": [
        {
            "id": "first-question",
            "prompt": "What is 2 x 3?",
            "answer_type": "number",
            "check": {"method": "exact_numeric", "expected": "6"},
            "hints": ["Think of 2 groups of 3."],
        }
    ],
    "sources": [{"title": "Test fixture source", "kind": "internal"}],
    "provenance": {"origin": "human_authored", "author": "Test Author", "created": "2026-10-11"},
    "verification": {"status": "ai_draft"},
    "version": "0.1.0",
}


def record(**overrides: Any) -> dict[str, Any]:
    """Return a copy of the base record with top-level keys replaced by overrides."""
    data = copy.deepcopy(BASE_RECORD)
    data.update(overrides)
    return data


def write_yaml(root: Path, relative: str, data: Any) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def published_record() -> dict[str, Any]:
    """A reviewed concept with a known answer key, used to test the paths students actually see."""
    return record(
        id=PUBLISHED_ID,
        title="Published test concept",
        aliases=["published alias"],
        keywords=["published keyword"],
        prerequisites=[],
        related=[],
        exercises=[
            {
                "id": "secret-product",
                "prompt": "Multiply 6 by 7 using the test concept.",
                "answer_type": "number",
                "check": {"method": "exact_numeric", "expected": PUBLISHED_ANSWER},
                "hints": ["HINT-ZERO-TEXT", "HINT-ONE-TEXT"],
                "feedback_correct": "Correct feedback.",
                "feedback_incorrect": "Incorrect feedback.",
            }
        ],
        verification={"status": "reviewed", "reviewed_by": "Test Reviewer", "reviewed_on": "2026-10-11"},
    )
