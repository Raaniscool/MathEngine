"""Understand what a learner typed: search, explain, lesson, practice, solve, or clarify.

This module is deterministic and never calls an AI model. It only decides WHAT the request is.
The answer comes from the knowledge library (retrieval) or from SymPy (solve), never from here.

Intent kinds:
  solve    - the text contains a math expression or equation, such as "7 times 8" or "2x + 3 = 7".
             The expression is extracted and checked by the math engine.
  practice - the learner wants questions, for example "practice fractions".
  lesson   - the learner wants to be taught, for example "teach me long division".
  explain  - the learner asks what something is or why, for example "explain long division".
  search   - a bare topic, for example "multiplication facts".
  clarify  - the text has no topic words, for example "help" or "I don't understand".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..math.expressions import ExpressionError, parse_equation, parse_expression
from .text import normalize, tokens

INTENT_KINDS = ("solve", "practice", "lesson", "explain", "search", "clarify")

_PRACTICE_WORDS = frozenset({"practice", "quiz", "drill", "exercise", "exercises", "question", "questions", "test"})
_LESSON_WORDS = frozenset({"teach", "lesson", "lessons", "tutorial", "learn", "course", "walk", "start", "begin"})
_EXPLAIN_WORDS = frozenset(
    {"explain", "define", "definition", "meaning", "mean", "understand", "understanding", "describe", "why", "how", "what", "help"}
)
_SOLVE_WORDS = frozenset({"solve", "calculate", "compute", "evaluate", "simplify", "answer", "result", "equals"})

_MATH_TOKEN = re.compile(r"^[0-9a-z().+\-*/^=]+$")
_HAS_DIGIT_OR_OPERATOR = re.compile(r"[0-9+\-*/^=()]")
_PUNCTUATION_EDGE = ".,?!:;\"'"


@dataclass(frozen=True)
class Intent:
    kind: str  # one of INTENT_KINDS
    expression: str | None  # the extracted math text, for kind == "solve"
    reason: str  # plain-words explanation, shown in developer mode

    def __post_init__(self) -> None:
        if self.kind not in INTENT_KINDS:
            raise ValueError(f"unknown intent kind: {self.kind}")


def _rewrite_operators(text: str) -> str:
    """Turn spoken operators into Python-style symbols that the restricted parser understands."""
    lowered = text.lower().replace("\u00d7", " * ").replace("\u00f7", " / ").replace("^", "**")
    lowered = re.sub(r"\bmultiplied\s+by\b", " * ", lowered)
    lowered = re.sub(r"\bdivided\s+by\b", " / ", lowered)
    lowered = re.sub(r"\bto\s+the\s+power\s+of\b", " ** ", lowered)
    lowered = re.sub(r"\bpower\s+of\b", " ** ", lowered)
    lowered = re.sub(r"\bsquared\b", " ** 2 ", lowered)
    lowered = re.sub(r"\bcubed\b", " ** 3 ", lowered)
    lowered = re.sub(r"\btimes\b", " * ", lowered)
    lowered = re.sub(r"\bplus\b", " + ", lowered)
    lowered = re.sub(r"\bminus\b", " - ", lowered)
    # "x" between two numbers (or a number and a bracket) means multiplication: "7 x 8", "2x" is left alone.
    lowered = re.sub(r"(?<=\d)\s+x\s+(?=[\d(])", " * ", lowered)
    return lowered


def extract_expression(text: str) -> str | None:
    """The longest run of math-looking words in the text that the restricted parser accepts, or None."""
    rewritten = _rewrite_operators(text)
    words = [word.strip(_PUNCTUATION_EDGE) for word in rewritten.split()]
    best: list[str] = []
    run: list[str] = []
    for word in words:
        # A plain word such as "what" or "is" is never math. Only tokens with a digit, an operator,
        # or a single letter (a variable such as x) can be part of an expression.
        if word and _MATH_TOKEN.match(word) and (len(word) == 1 or _HAS_DIGIT_OR_OPERATOR.search(word)):
            run.append(word)
            continue
        if _is_worth_checking(run) and len(run) > len(best):
            best = run
        run = []
    if _is_worth_checking(run) and len(run) > len(best):
        best = run
    if not best:
        return None
    # Trim leading or trailing single letters that are probably English words ("a 7 * 8").
    while best and best[0].isalpha() and len(best[0]) == 1 and len(best) > 1:
        best = best[1:]
    candidate = " ".join(best)
    if "=" in candidate:
        try:
            parse_equation(candidate)
        except ExpressionError:
            return None
        return candidate
    try:
        parse_expression(candidate)
    except ExpressionError:
        return None
    return candidate


def _is_worth_checking(run: list[str]) -> bool:
    """A run is worth parsing only if it has a number and an operator, or is an equation."""
    has_number = any(any(char.isdigit() for char in word) for word in run)
    has_operator = any(any(op in word for op in "+-*/^=") for word in run)
    has_variable = any(any(char.isalpha() for char in word) for word in run)  # "2x", "x", "y"
    return has_number and (has_operator or has_variable)


def _words(text: str) -> list[str]:
    return normalize(text).split()


def _has_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {' '.join(_words(text))} "


def classify(text: str) -> Intent:
    """Decide what the learner wants. Order: solve (with expression), practice, lesson, explain, search."""
    words = set(_words(text))
    expression = extract_expression(text)
    # Topic words only: a token that contains a digit ("2x") is part of the expression, not a topic.
    prose_terms = [term for term in tokens(text) if not any(char.isdigit() for char in term)]

    if expression is not None:
        if words & _PRACTICE_WORDS and prose_terms:
            return Intent("practice", None, "Practice request with a topic.")
        if words & (_LESSON_WORDS | _EXPLAIN_WORDS) and prose_terms:
            return Intent("explain", expression, "The request asks for an explanation of a topic; the expression is also checked.")
        return Intent("solve", expression, "A math expression was found and will be checked by the math engine.")

    if not prose_terms:
        return Intent("clarify", None, "No topic words were found.")
    if words & _PRACTICE_WORDS:
        return Intent("practice", None, "The request asks for practice questions.")
    if words & _LESSON_WORDS or _has_phrase(text, "how do i") or _has_phrase(text, "how to"):
        return Intent("lesson", None, "The request asks to be taught a topic.")
    if words & _EXPLAIN_WORDS or _has_phrase(text, "what is") or _has_phrase(text, "what are"):
        return Intent("explain", None, "The request asks what something is or why.")
    if words & _SOLVE_WORDS:
        return Intent("search", None, "The request names a topic after a solve word; searching for the topic.")
    return Intent("search", None, "A bare topic was entered; searching the library.")
