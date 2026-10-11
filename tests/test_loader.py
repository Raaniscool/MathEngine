"""Loader tests: broken libraries are reported, and a broken library never replaces a good index."""

from __future__ import annotations

import pytest
from helpers import record, write_yaml

from mathengine.knowledge.index import IndexBuildError, build_index
from mathengine.knowledge.loader import load_knowledge


def _issues(report) -> str:
    return "\n".join(str(issue) for issue in report.errors)


def test_repository_library_is_valid(knowledge_dir):
    report = load_knowledge(knowledge_dir)
    assert report.ok, _issues(report)
    assert len(report.records) >= 5


def test_invalid_yaml_is_reported(tmp_path):
    (tmp_path / "arithmetic").mkdir()
    (tmp_path / "arithmetic" / "broken.yaml").write_text("id: [unclosed", encoding="utf-8")
    assert "invalid YAML" in _issues(load_knowledge(tmp_path))


def test_record_in_wrong_subject_folder_is_reported(tmp_path):
    write_yaml(tmp_path, "algebra/sample.yaml", record())  # subject is arithmetic
    assert "must live in knowledge/arithmetic/" in _issues(load_knowledge(tmp_path))


def test_unknown_prerequisite_is_reported(tmp_path):
    write_yaml(tmp_path, "arithmetic/sample.yaml", record(prerequisites=["arithmetic.testing.missing"]))
    assert "references unknown concept 'arithmetic.testing.missing'" in _issues(load_knowledge(tmp_path))


def test_prerequisite_cycle_is_reported(tmp_path):
    write_yaml(tmp_path, "arithmetic/a.yaml", record(id="arithmetic.cycle.a", title="Cycle A", prerequisites=["arithmetic.cycle.b"]))
    write_yaml(tmp_path, "arithmetic/b.yaml", record(id="arithmetic.cycle.b", title="Cycle B", prerequisites=["arithmetic.cycle.a"]))
    assert "prerequisite cycle" in _issues(load_knowledge(tmp_path))


def test_duplicate_ids_are_reported(tmp_path):
    write_yaml(tmp_path, "arithmetic/one.yaml", record())
    write_yaml(tmp_path, "arithmetic/two.yaml", record(title="Another title"))
    assert "duplicate concept id" in _issues(load_knowledge(tmp_path))


def test_wrong_derivative_is_caught_by_the_math_checker(tmp_path):
    exercise = {"id": "power", "prompt": "Differentiate f(x) = x^5 please.", "answer_type": "expression",
                "check": {"method": "derivative", "function": "x^5", "expected": "5*x^3"}}
    write_yaml(tmp_path, "arithmetic/sample.yaml", record(exercises=[exercise]))
    assert "is not the derivative" in _issues(load_knowledge(tmp_path))


def test_wrong_solution_is_caught_by_the_math_checker(tmp_path):
    exercise = {"id": "solve", "prompt": "Solve 3x + 4 = 19 for x.", "answer_type": "equation_solution",
                "check": {"method": "solve_equation", "equation": "3*x + 4 = 19", "expected": "6"}}
    write_yaml(tmp_path, "arithmetic/sample.yaml", record(exercises=[exercise]))
    assert "does not satisfy" in _issues(load_knowledge(tmp_path))


def test_numeric_answer_with_variables_is_caught(tmp_path):
    exercise = {"id": "num", "prompt": "What number is x times two?", "answer_type": "number",
                "check": {"method": "exact_numeric", "expected": "2*x"}}
    write_yaml(tmp_path, "arithmetic/sample.yaml", record(exercises=[exercise]))
    assert "must be numbers" in _issues(load_knowledge(tmp_path))


def test_false_formula_identity_is_caught(tmp_path):
    formula = {"name": "Wrong law", "expression": "a^m * a^n", "result": "a^(m*n)"}
    write_yaml(tmp_path, "arithmetic/sample.yaml", record(formulas=[formula]))
    assert "not provably equal" in _issues(load_knowledge(tmp_path))


def test_index_is_not_rebuilt_when_library_is_invalid(tmp_path):
    good_dir = tmp_path / "good"
    write_yaml(good_dir, "arithmetic/sample.yaml", record())
    index_path = tmp_path / "data" / "knowledge.sqlite"
    build_index(load_knowledge(good_dir), index_path)
    original = index_path.read_bytes()

    bad_dir = tmp_path / "bad"
    write_yaml(bad_dir, "arithmetic/sample.yaml", record(titel="typo"))
    with pytest.raises(IndexBuildError):
        build_index(load_knowledge(bad_dir), index_path)
    assert index_path.read_bytes() == original  # the good index survives untouched
