"""Deterministic answer checking.

Every checked answer goes through one explicit *method*. The methods are:

* exact_numeric        - the student's answer must equal a stored number exactly.
* symbolic_equivalence - the student's expression must equal the stored expression for all values.
* derivative           - the student's expression must equal the SymPy derivative of a stored function.
* solve_equation       - the student's value must satisfy a stored equation.
* none                 - no automatic method exists; the result is reported as UNVERIFIABLE.

Honesty rule: a result is only marked CORRECT or INCORRECT (with ``verified=True``) when a
deterministic method reached a conclusion. If the engine cannot decide, it says UNVERIFIABLE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import sympy

from .expressions import ExpressionError, parse_equation, parse_expression

METHODS = ("exact_numeric", "symbolic_equivalence", "derivative", "solve_equation", "none")

_TOLERANCE = 1e-9
# Fixed sample points used to disprove equality numerically. Chosen to avoid obvious poles.
_SAMPLE_POINTS = (
    sympy.Rational(2, 7),
    sympy.Rational(-3, 5),
    sympy.Rational(11, 4),
    sympy.Integer(3),
    sympy.Rational(-5, 2),
)


class Verdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INVALID_INPUT = "invalid_input"  # the student's text could not be read as the expected kind of answer
    UNVERIFIABLE = "unverifiable"  # the engine could not reach a conclusion


@dataclass(frozen=True)
class CheckSpec:
    """Plain description of how an answer is checked. Mirrors the knowledge-record 'check' block."""

    method: str
    expected: str | None = None
    function: str | None = None
    variable: str = "x"
    equation: str | None = None
    unverifiable_reason: str | None = None


@dataclass(frozen=True)
class CheckResult:
    verdict: Verdict
    method: str
    message: str
    verified: bool = False  # True only when a deterministic method reached a conclusion

    @property
    def is_correct(self) -> bool:
        return self.verdict is Verdict.CORRECT


def check_answer(student_text: str, spec: CheckSpec) -> CheckResult:
    """Grade a student's answer against a check specification."""
    if spec.method not in METHODS:
        raise ValueError(f"unknown check method: {spec.method!r}")
    if spec.method == "none":
        reason = spec.unverifiable_reason or "This answer cannot be checked automatically."
        return CheckResult(Verdict.UNVERIFIABLE, "none", reason)
    if not isinstance(student_text, str) or not student_text.strip():
        return CheckResult(Verdict.INVALID_INPUT, spec.method, "Please enter an answer.")

    try:
        if spec.method == "solve_equation":
            return _check_solution(student_text, spec)
        target = _target_expression(spec)
    except ExpressionError as exc:
        # The stored answer itself is broken. That is a content problem, not a student mistake.
        return CheckResult(
            Verdict.UNVERIFIABLE, spec.method, f"The stored answer could not be checked: {exc}"
        )

    try:
        student = parse_expression(student_text)
    except ExpressionError as exc:
        return CheckResult(Verdict.INVALID_INPUT, spec.method, f"I could not read that answer: {exc}")

    if spec.method == "exact_numeric" and student.free_symbols:
        return CheckResult(Verdict.INVALID_INPUT, spec.method, "Enter a number, without variables.")

    same = expressions_equal(student, target)
    if same is True:
        return CheckResult(Verdict.CORRECT, spec.method, "Correct.", verified=True)
    if same is False:
        return CheckResult(
            Verdict.INCORRECT, spec.method, "That is not equal to the correct answer.", verified=True
        )
    return CheckResult(
        Verdict.UNVERIFIABLE,
        spec.method,
        "The engine could not confirm whether this answer is equivalent to the correct one.",
    )


def verify_definition(spec: CheckSpec) -> list[str]:
    """Check that a stored answer is internally consistent. Returns problems; an empty list means OK.

    Used by knowledge validation so that a wrong 'expected' value is caught before it reaches a student.
    """
    if spec.method == "none":
        return []
    if spec.method not in METHODS:
        return [f"unknown check method '{spec.method}'"]
    try:
        if spec.method == "solve_equation":
            return _verify_solution_definition(spec)
        if spec.method == "derivative":
            if not spec.expected:
                return ["derivative checks need an 'expected' derivative"]
            stored = parse_expression(spec.expected)
            truth = _target_expression(spec)
            if expressions_equal(stored, truth) is True:
                return []
            return [f"expected answer '{spec.expected}' is not the derivative of '{spec.function}'"]
        if not spec.expected:
            return [f"method '{spec.method}' needs an 'expected' answer"]
        stored = parse_expression(spec.expected)
        if spec.method == "exact_numeric" and stored.free_symbols:
            return [f"exact_numeric answers must be numbers, but '{spec.expected}' has variables"]
        return []
    except ExpressionError as exc:
        return [str(exc)]


def expressions_equal(first: sympy.Expr, second: sympy.Expr) -> bool | None:
    """Return True if provably equal, False if provably different, None if undecided.

    Step 1: symbolic simplification. If the difference simplifies to zero, they are equal.
    Step 2: numeric sampling. If they differ at any sample point where both are defined, they are
            different. Agreement at the sample points is NOT proof, so the result stays undecided.
    """
    if sympy.simplify(first - second) == 0:
        return True
    symbols = first.free_symbols | second.free_symbols
    if not symbols:
        return False if _is_nonzero_number(sympy.simplify(first - second)) else None
    for point in _SAMPLE_POINTS:
        substitution = {symbol: point for symbol in symbols}
        try:
            left = complex(sympy.N(first.subs(substitution)))
            right = complex(sympy.N(second.subs(substitution)))
        except (TypeError, ValueError, ArithmeticError):
            continue  # undefined at this point (for example log(0)); try another point
        if not (math.isfinite(left.real) and math.isfinite(right.real)):
            continue
        scale = max(1.0, abs(left), abs(right))
        if abs(left - right) > _TOLERANCE * scale:
            return False
    return None


def texts_equivalent(first_text: str, second_text: str) -> bool | None:
    """Convenience wrapper around expressions_equal for two expression strings."""
    return expressions_equal(parse_expression(first_text), parse_expression(second_text))


def _target_expression(spec: CheckSpec) -> sympy.Expr:
    if spec.method == "derivative":
        if not spec.function:
            raise ExpressionError("no function is given for the derivative")
        return sympy.diff(parse_expression(spec.function), sympy.Symbol(spec.variable))
    if not spec.expected:
        raise ExpressionError("no expected answer is stored")
    return parse_expression(spec.expected)


def _is_nonzero_number(value: sympy.Expr) -> bool:
    if value.free_symbols:
        return False
    if value.is_zero is False:
        return True
    try:
        number = complex(sympy.N(value, 30))
    except (TypeError, ValueError, ArithmeticError):
        return False
    return math.isfinite(number.real) and abs(number) > _TOLERANCE


def _check_solution(student_text: str, spec: CheckSpec) -> CheckResult:
    if not spec.equation:
        raise ExpressionError("no equation is stored")
    left, right = parse_equation(spec.equation)
    residual_equation = left - right
    variable = sympy.Symbol(spec.variable)

    text = student_text.strip()
    if "=" in text:
        name, _, value_text = text.partition("=")
        if name.strip() != spec.variable:
            return CheckResult(
                Verdict.INVALID_INPUT,
                "solve_equation",
                f"Write only the value of {spec.variable}, for example 4 or {spec.variable} = 4.",
            )
        text = value_text

    try:
        value = parse_expression(text)
    except ExpressionError as exc:
        return CheckResult(Verdict.INVALID_INPUT, "solve_equation", f"I could not read that answer: {exc}")
    if value.free_symbols:
        return CheckResult(Verdict.INVALID_INPUT, "solve_equation", "The answer must be a number.")

    residual = sympy.simplify(residual_equation.subs(variable, value))
    if residual == 0:
        return CheckResult(
            Verdict.CORRECT,
            "solve_equation",
            f"Correct: {spec.variable} = {value} satisfies the equation.",
            verified=True,
        )
    if _is_nonzero_number(residual):
        return CheckResult(
            Verdict.INCORRECT,
            "solve_equation",
            f"Not quite: substituting {spec.variable} = {value} does not satisfy the equation.",
            verified=True,
        )
    return CheckResult(
        Verdict.UNVERIFIABLE,
        "solve_equation",
        "The engine could not confirm whether this value satisfies the equation.",
    )


def _verify_solution_definition(spec: CheckSpec) -> list[str]:
    if not spec.equation or not spec.expected:
        return ["solve_equation checks need both an 'equation' and an 'expected' solution"]
    left, right = parse_equation(spec.equation)
    value = parse_expression(spec.expected)
    if value.free_symbols:
        return [f"the expected solution '{spec.expected}' must be a number"]
    residual = sympy.simplify((left - right).subs(sympy.Symbol(spec.variable), value))
    if residual == 0:
        return []
    if _is_nonzero_number(residual):
        return [f"the expected solution '{spec.expected}' does not satisfy '{spec.equation}'"]
    return [f"could not confirm that '{spec.expected}' satisfies '{spec.equation}'"]
