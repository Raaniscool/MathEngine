"""Architecture guard. The knowledge and math layers must not depend on the AI layer or on HTTP.

Why: the spec says Ollama is non-authoritative. If the deterministic core could import the AI client,
a model's output could influence grading or the authoritative index. This test fails if that happens.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "mathengine"

# Core packages that must stay independent of the AI client and of HTTP.
CORE = ["math", "learning", "knowledge"]


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            found.append((module, node.lineno))
    return found


def _core_files() -> list[Path]:
    files: list[Path] = []
    for package in CORE:
        files += sorted((PACKAGE / package).rglob("*.py"))
    return files


def test_core_packages_exist_and_are_scanned():
    files = _core_files()
    assert len(files) >= 10, "architecture guard scanned too few files; did the layout change?"


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_core_module_does_not_import_ai_or_http(path: Path):
    offending = []
    for module, line in _imports(path):
        if module.startswith("mathengine.ai") or module == "httpx" or module.startswith("httpx."):
            offending.append(f"line {line}: {module}")
        if module.startswith("..ai") or module == "..ai" or module.startswith("..ai."):
            offending.append(f"line {line}: {module}")
        if module.startswith(".ai") or module.startswith("..api") or module.startswith("...ai"):
            offending.append(f"line {line}: {module}")
    assert offending == [], f"{path.relative_to(PACKAGE)} must not depend on the AI layer or HTTP: {offending}"


def test_ai_layer_is_the_only_httpx_user_outside_the_api():
    """Only the AI client and the API layer may import httpx. Everything else stays transport-free."""
    users = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        if any(part in {"__pycache__"} for part in path.parts):
            continue
        if any(module == "httpx" or module.startswith("httpx.") for module, _ in _imports(path)):
            users.add(path.relative_to(PACKAGE).parts[0])
    assert users <= {"ai", "api"}, f"unexpected httpx users: {sorted(users)}"
