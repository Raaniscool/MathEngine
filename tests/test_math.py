"""Mathematical engine tests: safe parsing, exact evaluation and honest answer checking."""

from __future__ import annotations

import pytest
import sympy

from mathengine.math.checker import CheckSpec, Verdict, check_answer, verify_definition
from mathengine.math.evaluate import evaluate_expression
from mathengine.math.expressions import ExpressionError, parse_equation, parse_expression


# --- parsing -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2x+3", 2 * sympy.Symbol("x") + 3),
        ("3(x+1)", 3 * sympy.Symbol("x") + 3),
        ("2^3^2", sympy.Integer(512)),  # right-associative: 2^(3^2)
        ("-2^2", sympy.Integer(-4)),  # the power binds tighter than unary minus
        ("1/2 + 0.5", sympy.Integer(1)),  # decimals are exact
        ("sqrt(8)", 2 * sympy.sqrt(2)),
        ("2*pi", 2 * sympy.pi),
    ],
)
def test_supported_expressions_parse_exactly(text, expected):
    assert sympy.simplify(parse_expression(text) - expected) == 0


@pytest.mark.parametrize(
    "hostile",
    [
        '__import__("os").system("echo unsafe")',
        'open("/etc/passwd")',
        "x.__class__",
        "import os",
        "lambda x: x",
        "exec('1')",
        "x; y",
        "[1, 2]",
    ],
)
def test_code_like_input_is_rejected_without_execution(hostile):
    with pytest.raises(ExpressionError):
        parse_expression(hostile)


def test_equation_is_not_accepted_as_an_expression():
    with pytest.raises(ExpressionError, match="equation"):
        parse_expression("x = 2")


def test_division_by_zero_is_reported():
    with pytest.raises(ExpressionError, match="division by zero"):
        parse_expression("1/0")


def test_huge_numeric_power_is_refused_to_protect_the_server():
    with pytest.raises(ExpressionError, match="too large"):
        parse_expression("2^(10^9)")


def test_multi_letter_unknown_names_are_rejected_with_advice():
    with pytest.raises(ExpressionError, match="write xy as x\\*y"):
        parse_expression("xy")


def test_overlong_input_is_rejected():
    with pytest.raises(ExpressionError, match="longer than"):
        parse_expression("1+" * 150 + "1")


def test_parse_equation_splits_both_sides():
    left, right = parse_equation("3*x + 4 = 19")
    assert sympy.simplify(left - (3 * sympy.Symbol("x") + 4)) == 0
    assert right == 19


def test_evaluate_expression_returns_exact_and_approximate_forms():
    result = evaluate_expression("sqrt(8)")
    assert result.exact == "2*sqrt(2)"
    assert result.approximate.startswith("2.82842")
    assert result.is_numeric


# --- checking student answers -------------------------------------------------------------

def test_exact_numeric_accepts_equal_values_written_differently():
    spec = CheckSpec("exact_numeric", expected="1/2")
    assert check_answer("0.5", spec).verdict is Verdict.CORRECT
    assert check_answer("2/4", spec).verdict is Verdict.CORRECT


def test_exact_numeric_flags_wrong_numbers_as_verified_incorrect():
    result = check_answer("13", CheckSpec("exact_numeric", expected="12"))
    assert result.verdict is Verdict.INCORRECT
    assert result.verified is True


def test_exact_numeric_rejects_variables_as_invalid_input():
    result = check_answer("x", CheckSpec("exact_numeric", expected="12"))
    assert result.verdict is Verdict.INVALID_INPUT
    assert result.verified is False


def test_symbolic_equivalence_accepts_reordered_expressions():
    assert check_answer("y*12", CheckSpec("symbolic_equivalence", expected="12*y")).verdict is Verdict.CORRECT


def test_symbolic_equivalence_accepts_trig_identities():
    spec = CheckSpec("symbolic_equivalence", expected="1")
    assert check_answer("sin(x)^2 + cos(x)^2", spec).verdict is Verdict.CORRECT


def test_symbolic_equivalence_rejects_different_functions():
    result = check_answer("sin(x)", CheckSpec("symbolic_equivalence", expected="cos(x)"))
    assert result.verdict is Verdict.INCORRECT and result.verified


def test_derivative_check_uses_sympy_not_the_stored_text():
    spec = CheckSpec("derivative", function="x^5", expected="5*x^4")
    assert check_answer("5x^4", spec).verdict is Verdict.CORRECT
    assert check_answer("5x^3", spec).verdict is Verdict.INCORRECT


def test_solve_equation_accepts_bare_value_or_assignment():
    spec = CheckSpec("solve_equation", equation="3*x + 4 = 19", expected="5")
    assert check_answer("5", spec).verdict is Verdict.CORRECT
    assert check_answer("x = 5", spec).verdict is Verdict.CORRECT
    assert check_answer("4", spec).verdict is Verdict.INCORRECT


def test_solve_equation_rejects_assignment_to_the_wrong_name():
    result = check_answer("y = 5", CheckSpec("solve_equation", equation="3*x + 4 = 19", expected="5"))
    assert result.verdict is Verdict.INVALID_INPUT


def test_fraction_solutions_match_decimal_entries_exactly():
    assert check_answer("0.4", CheckSpec("solve_equation", equation="5*x = 2", expected="2/5")).verdict is Verdict.CORRECT


def test_methods_without_automatic_check_are_honestly_unverifiable():
    result = check_answer("anything", CheckSpec("none", unverifiable_reason="Free-form proof."))
    assert result.verdict is Verdict.UNVERIFIABLE
    assert result.verified is False
    assert "Free-form proof." in result.message


def test_empty_answer_is_invalid_input():
    assert check_answer("   ", CheckSpec("exact_numeric", expected="1")).verdict is Verdict.INVALID_INPUT


def test_broken_stored_answer_is_reported_as_unverifiable_not_incorrect():
    result = check_answer("3", CheckSpec("exact_numeric", expected="((("))
    assert result.verdict is Verdict.UNVERIFIABLE


# --- checking stored answers --------------------------------------------------------------

def test_verify_definition_accepts_consistent_answers():
    assert verify_definition(CheckSpec("derivative", function="x^5", expected="5*x^4")) == []
    assert verify_definition(CheckSpec("solve_equation", equation="3*x+4=19", expected="5")) == []


def test_verify_definition_reports_inconsistent_answers():
    assert verify_definition(CheckSpec("derivative", function="x^5", expected="5*x^3"))
    assert verify_definition(CheckSpec("solve_equation", equation="3*x+4=19", expected="6"))
