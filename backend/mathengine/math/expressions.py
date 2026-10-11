"""Safe parser for mathematical expressions typed by students or supplied in records.

Why not `sympy.sympify(text)` or Python's `eval`?
Those execute Python code. This parser only understands a small grammar:

* numbers (integers and decimals; decimals become exact fractions, so 0.5 is 1/2),
* single-letter variables such as x, y, n,
* the operators + - * / ^ (and ** as an alias for ^), and parentheses,
* a fixed list of functions (sqrt, sin, cos, tan, exp, log, ln) and the constant pi.

It builds SymPy objects directly from these tokens, so no user-supplied Python is ever run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sympy


class ExpressionError(ValueError):
    """Raised when text is not a supported expression.

    The message is written to be shown to students, so it describes the problem in plain words.
    """


MAX_LENGTH = 200  # characters
MAX_TOKENS = 120
MAX_EXPONENT = 10_000  # guards against huge numeric powers such as 10^(10^9)

FUNCTIONS = {
    "sqrt": sympy.sqrt,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "exp": sympy.exp,
    "log": sympy.log,  # natural logarithm
    "ln": sympy.log,
}
CONSTANTS = {"pi": sympy.pi}

_TOKEN_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)|([A-Za-z]+)|(\*\*|[-+*/^()=,])")


@dataclass(frozen=True)
class _Token:
    kind: str  # "NUM", "NAME", or "OP"
    text: str
    pos: int  # zero-based position in the original text


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char.isspace():
            pos += 1
            continue
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ExpressionError(f"unexpected character '{char}' at position {pos + 1}")
        if match.group(1) is not None:
            kind = "NUM"
        elif match.group(2) is not None:
            kind = "NAME"
        else:
            kind = "OP"
        tokens.append(_Token(kind, match.group(0), pos))
        if len(tokens) > MAX_TOKENS:
            raise ExpressionError("the expression is too long")
        pos = match.end()
    return tokens


def _power(base: sympy.Expr, exponent: sympy.Expr) -> sympy.Expr:
    if base.is_number and isinstance(exponent, sympy.Integer) and abs(int(exponent)) > MAX_EXPONENT:
        raise ExpressionError(f"the exponent {exponent} is too large")
    return base**exponent


def _divide(numerator: sympy.Expr, denominator: sympy.Expr) -> sympy.Expr:
    if denominator.is_zero is True:
        raise ExpressionError("division by zero")
    return numerator / denominator


class _Parser:
    """Recursive-descent parser. Grammar (lowest to highest precedence):

    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor | implicit factor)*
    factor := ('+' | '-') factor | power
    power  := atom ('^' factor)?          # right-associative
    atom   := NUM | NAME | NAME '(' expr ')' | '(' expr ')'
    """

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._index = 0

    def _peek(self) -> _Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _advance(self) -> _Token:
        token = self._peek()
        if token is None:
            raise ExpressionError("the expression ends unexpectedly")
        self._index += 1
        return token

    def _accept_op(self, *operators: str) -> str | None:
        token = self._peek()
        if token is not None and token.kind == "OP" and token.text in operators:
            self._index += 1
            return token.text
        return None

    def _expect_op(self, operator: str) -> None:
        if self._accept_op(operator) is None:
            token = self._peek()
            found = "the end of the expression" if token is None else f"'{token.text}'"
            raise ExpressionError(f"expected '{operator}' but found {found}")

    def parse(self) -> sympy.Expr:
        if not self._tokens:
            raise ExpressionError("the expression is empty")
        result = self._expr()
        leftover = self._peek()
        if leftover is not None:
            if leftover.text == "=":
                raise ExpressionError("this is an equation; enter a single expression here")
            raise ExpressionError(f"unexpected '{leftover.text}' at position {leftover.pos + 1}")
        return result

    def _expr(self) -> sympy.Expr:
        node = self._term()
        while (op := self._accept_op("+", "-")) is not None:
            right = self._term()
            node = node + right if op == "+" else node - right
        return node

    def _term(self) -> sympy.Expr:
        node = self._factor()
        while True:
            op = self._accept_op("*", "/")
            if op is not None:
                right = self._factor()
                node = node * right if op == "*" else _divide(node, right)
                continue
            # Implicit multiplication, e.g. "2x", "3(x+1)", "2pi".
            nxt = self._peek()
            if nxt is not None and (nxt.kind in ("NUM", "NAME") or nxt.text == "("):
                node = node * self._factor()
                continue
            return node

    def _factor(self) -> sympy.Expr:
        op = self._accept_op("+", "-")
        if op is not None:
            operand = self._factor()
            return -operand if op == "-" else operand
        return self._power()

    def _power(self) -> sympy.Expr:
        base = self._atom()
        if self._accept_op("^", "**") is not None:
            return _power(base, self._factor())
        return base

    def _atom(self) -> sympy.Expr:
        token = self._advance()
        if token.kind == "NUM":
            return sympy.Rational(token.text)
        if token.kind == "NAME":
            return self._name(token)
        if token.text == "(":
            inner = self._expr()
            self._expect_op(")")
            return inner
        raise ExpressionError(f"unexpected '{token.text}' at position {token.pos + 1}")

    def _name(self, token: _Token) -> sympy.Expr:
        name = token.text
        if name in FUNCTIONS:
            if self._accept_op("(") is None:
                raise ExpressionError(f"'{name}' needs parentheses, for example {name}(x)")
            argument = self._expr()
            self._expect_op(")")
            return FUNCTIONS[name](argument)
        if name in CONSTANTS:
            return CONSTANTS[name]
        if len(name) == 1:
            return sympy.Symbol(name)
        raise ExpressionError(
            f"unknown name '{name}'. Variables are single letters, so write xy as x*y"
        )


def parse_expression(text: str) -> sympy.Expr:
    """Parse one expression into an exact SymPy expression. Raises ExpressionError on any problem."""
    if not isinstance(text, str):
        raise ExpressionError("the expression must be text")
    stripped = text.strip()
    if not stripped:
        raise ExpressionError("the expression is empty")
    if len(stripped) > MAX_LENGTH:
        raise ExpressionError(f"the expression is longer than {MAX_LENGTH} characters")
    expression = _Parser(_tokenize(stripped)).parse()
    if expression.has(sympy.nan, sympy.zoo):
        raise ExpressionError("the expression is undefined (for example, division by zero)")
    return expression


def parse_equation(text: str) -> tuple[sympy.Expr, sympy.Expr]:
    """Split 'left = right' and parse both sides."""
    if not isinstance(text, str) or text.count("=") != 1:
        raise ExpressionError("an equation must contain exactly one '='")
    left, right = text.split("=")
    return parse_expression(left), parse_expression(right)
