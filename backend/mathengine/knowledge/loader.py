"""Load and validate the knowledge library from disk.

Validation runs in four layers. Any error stops an index rebuild, so a bad record can never
replace a good index:

1. YAML syntax.
2. Schema (models.py): field names, types, ranges, required fields.
3. Structure: the record lives in knowledge/<subject>/, ids are unique, references resolve,
   prerequisites contain no cycles.
4. Mathematics: formulas parse, formula identities hold, every stored answer is consistent
   with its check (for example, the expected derivative really is the derivative).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

import re

from ..math.checker import expressions_equal, texts_equivalent, verify_definition
from ..math.expressions import ExpressionError, parse_expression
from .models import Concept


@dataclass(frozen=True)
class Issue:
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


@dataclass(frozen=True)
class LoadedRecord:
    relative_path: str  # POSIX-style path relative to the knowledge directory
    concept: Concept
    sha256: str  # hash of the file bytes, used to fingerprint the whole library


@dataclass
class LoadReport:
    records: list[LoadedRecord] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def fingerprint(self) -> str:
        """Stable hash of every record file. Changes whenever any knowledge file changes."""
        digest = hashlib.sha256()
        for record in sorted(self.records, key=lambda item: item.relative_path):
            digest.update(f"{record.relative_path}:{record.sha256}\n".encode())
        return digest.hexdigest()


def load_knowledge(knowledge_dir: Path) -> LoadReport:
    """Read and validate every .yaml/.yml file below knowledge_dir."""
    report = LoadReport()
    if not knowledge_dir.is_dir():
        report.errors.append(Issue(str(knowledge_dir), "knowledge directory does not exist"))
        return report

    parsed: list[LoadedRecord] = []
    for path in sorted(knowledge_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".yaml", ".yml"):
            continue
        relative = path.relative_to(knowledge_dir)
        location = relative.as_posix()
        raw = path.read_bytes()
        file_errors: list[Issue] = []

        try:
            data = yaml.safe_load(raw.decode("utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as exc:
            report.errors.append(Issue(location, f"invalid YAML: {exc}"))
            continue
        if not isinstance(data, dict):
            report.errors.append(Issue(location, "a record must be a YAML mapping"))
            continue

        try:
            concept = Concept.model_validate(data)
        except ValidationError as exc:
            for error in exc.errors():
                field_path = ".".join(str(part) for part in error["loc"]) or "record"
                file_errors.append(Issue(location, f"{field_path}: {error['msg']}"))
            report.errors.extend(file_errors)
            continue

        parts = relative.parts
        if len(parts) != 2 or parts[0] != concept.subject:
            file_errors.append(
                Issue(location, f"records must live in knowledge/{concept.subject}/ (subject '{concept.subject}')")
            )
        for message in verify_concept_math(concept):
            file_errors.append(Issue(location, message))

        report.errors.extend(file_errors)
        if not file_errors:
            parsed.append(LoadedRecord(location, concept, hashlib.sha256(raw).hexdigest()))

    report.errors.extend(_check_cross_references(parsed))
    report.records = parsed
    return report


def verify_concept_math(concept: Concept) -> list[str]:
    """Mathematical checks for one record. Returns human-readable problems."""
    problems: list[str] = []
    for formula in concept.formulas:
        try:
            parse_expression(formula.expression)
            if formula.result is not None:
                parse_expression(formula.result)
                same = texts_equivalent(formula.expression, formula.result)
                if same is not True:
                    problems.append(
                        f"formula '{formula.name}': '{formula.expression}' is not provably equal to "
                        f"'{formula.result}' (state a condition, or fix the formula)"
                    )
        except ExpressionError as exc:
            problems.append(f"formula '{formula.name}': {exc}")

    for exercise in concept.exercises:
        for problem in verify_definition(exercise.check.to_spec()):
            problems.append(f"exercise '{exercise.id}': {problem}")
    problems.extend(worked_example_problems(concept))
    return problems


_TIMES_X = re.compile(r"(?<=[\d)])\s*x\s*(?=[\d(])")


def _as_math(text: str) -> str:
    """Turn school notation into the restricted parser's notation: 7 x 8 -> 7 * 8, 2^3 -> 2**3."""
    converted = text.replace("\u00d7", "*").replace("\u00f7", "/").replace("\u00b7", "*").replace("^", "**")
    return _TIMES_X.sub(" * ", converted)


def worked_example_problems(concept: Concept) -> list[str]:
    """Check the arithmetic in worked examples. Returns problems; empty means every checkable step is right.

    Only steps that are pure number chains are checked, such as "6 x 10 = 60" or "60 - 6 = 54".
    Prose steps and equation-solving steps (which contain variables) are not checked by this
    function. Their correctness is not machine-verified. The answer must equal the final checked value.
    """
    problems: list[str] = []
    for example in concept.worked_examples:
        last_value: str | None = None
        for step in example.steps:
            text = _as_math(step.strip().rstrip("."))
            if "=" not in text:
                continue
            parts = [part.strip() for part in text.split("=")]
            try:
                expressions = [parse_expression(part) for part in parts]
            except ExpressionError:
                continue  # prose mixed with maths: not checkable here
            if any(expression.free_symbols for expression in expressions):
                continue  # equations with variables are not pure arithmetic
            for left, right in zip(parts, parts[1:]):
                if texts_equivalent(left, right) is not True:
                    problems.append(
                        f"worked example '{example.title}': step '{step}' is wrong ('{left}' is not '{right}')"
                    )
            last_value = parts[-1]
        if last_value is None:
            continue
        try:
            answer = parse_expression(_as_math(example.answer))
        except ExpressionError:
            continue
        if answer.free_symbols:
            continue  # symbolic answers ("x^7") are not compared with numeric steps
        if expressions_equal(answer, parse_expression(last_value)) is not True:
            problems.append(
                f"worked example '{example.title}': the answer '{example.answer}' does not match the steps ('{last_value}')"
            )
    return problems


def _check_cross_references(records: list[LoadedRecord]) -> list[Issue]:
    issues: list[Issue] = []
    by_id: dict[str, LoadedRecord] = {}
    for record in records:
        existing = by_id.get(record.concept.id)
        if existing is not None:
            issues.append(
                Issue(
                    record.relative_path,
                    f"duplicate concept id '{record.concept.id}' (also in {existing.relative_path})",
                )
            )
        else:
            by_id[record.concept.id] = record

    for record in records:
        for reference in record.concept.prerequisites + record.concept.related:
            if reference not in by_id:
                issues.append(
                    Issue(
                        record.relative_path,
                        f"references unknown concept '{reference}' (check the id and that its file validates)",
                    )
                )

    issues.extend(_prerequisite_cycles(by_id))
    return issues


def _prerequisite_cycles(by_id: dict[str, LoadedRecord]) -> list[Issue]:
    """Depth-first search over prerequisite edges. Reports each record that sits on a cycle."""
    issues: list[Issue] = []
    state: dict[str, int] = {}  # 0/absent = unvisited, 1 = on stack, 2 = done
    stack: list[str] = []

    def visit(concept_id: str) -> None:
        state[concept_id] = 1
        stack.append(concept_id)
        for prerequisite in by_id[concept_id].concept.prerequisites:
            if prerequisite not in by_id:
                continue  # reported as an unknown reference elsewhere
            if state.get(prerequisite) == 1:
                cycle = stack[stack.index(prerequisite):] + [prerequisite]
                issues.append(
                    Issue(by_id[concept_id].relative_path, f"prerequisite cycle: {' -> '.join(cycle)}")
                )
            elif state.get(prerequisite) is None:
                visit(prerequisite)
        stack.pop()
        state[concept_id] = 2

    for concept_id in sorted(by_id):
        if concept_id not in state:
            visit(concept_id)
    return issues
