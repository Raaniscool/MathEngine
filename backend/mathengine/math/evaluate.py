"""Exact evaluation of a single expression typed by the user (used by the calculator-style endpoint)."""

from __future__ import annotations

from dataclasses import dataclass

import sympy

from .expressions import parse_expression


@dataclass(frozen=True)
class EvaluationResult:
    exact: str  # simplified exact form, e.g. "2*sqrt(2)" or "3/2"
    latex: str
    approximate: str | None  # decimal approximation, only when the expression has no variables
    is_numeric: bool


def evaluate_expression(text: str) -> EvaluationResult:
    """Simplify an expression exactly. Raises ExpressionError for unsupported input."""
    expression = sympy.simplify(parse_expression(text))
    is_numeric = not expression.free_symbols
    approximate = str(sympy.N(expression, 12)) if is_numeric else None
    return EvaluationResult(
        exact=sympy.sstr(expression),
        latex=sympy.latex(expression),
        approximate=approximate,
        is_numeric=is_numeric,
    )
