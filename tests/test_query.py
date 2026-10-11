"""Intent classification: each request is read as search, explain, lesson, solve, practice, or clarify."""
from __future__ import annotations

import pytest

from mathengine.knowledge.query import classify


@pytest.mark.parametrize(
    ("text", "kind", "expression"),
    [
        ("7 x 8", "solve", "7 * 8"),
        ("7 times 8", "solve", "7 * 8"),
        ("what is 2x + 3 = 7", "solve", "2x + 3 = 7"),
        ("solve for x", "clarify", None),  # no equation given: ask for one
        ("I don't understand", "clarify", None),  # no topic: ask what to explain
        ("help", "clarify", None),
        ("practice fractions", "practice", None),
        ("teach me long division", "lesson", None),
        ("explain long division", "explain", None),
        ("multiplication facts", "search", None),
    ],
)
def test_requests_are_classified_by_what_they_ask_for(text, kind, expression):
    intent = classify(text)
    assert intent.kind == kind
    assert intent.expression == expression
    assert intent.reason  # always explained in plain words for developer mode
