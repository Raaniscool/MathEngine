"""Shared fixtures. Every test gets its own temporary data directory, so no test touches real user data."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import PUBLISHED_ANSWER, PUBLISHED_ID, published_record
from mathengine.config import Settings
from mathengine.knowledge.index import build_index
from mathengine.knowledge.loader import load_knowledge
from mathengine.knowledge.store import KnowledgeStore

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"


@pytest.fixture
def knowledge_dir() -> Path:
    return KNOWLEDGE_DIR


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(
        knowledge_dir=KNOWLEDGE_DIR,
        data_dir=data_dir,
        ollama_url="http://ollama.test",
        ollama_model="test-model",
    )


@pytest.fixture
def built_index(data_dir: Path) -> Path:
    """The AUTHORITATIVE index built from the real library. It contains no drafts."""
    report = load_knowledge(KNOWLEDGE_DIR)
    assert report.ok, [str(issue) for issue in report.errors]
    return build_index(report, data_dir / "generated" / "knowledge.sqlite").index_path


@pytest.fixture
def dev_index(data_dir: Path) -> Path:
    """The DEVELOPER PREVIEW index built from the real library. It contains every record, drafts included."""
    report = load_knowledge(KNOWLEDGE_DIR)
    assert report.ok, [str(issue) for issue in report.errors]
    return build_index(report, data_dir / "generated" / "knowledge-dev.sqlite", include_drafts=True).index_path


@pytest.fixture
def store(dev_index: Path) -> KnowledgeStore:
    """The full library, drafts included. Used by tests that exercise draft content on purpose."""
    return KnowledgeStore.open(dev_index, expect_drafts=True)


@pytest.fixture
def authoritative_store(built_index: Path) -> KnowledgeStore:
    return KnowledgeStore.open(built_index)


@pytest.fixture
def published_store(tmp_path: Path) -> KnowledgeStore:
    """A small index containing one reviewed concept, so the visible (non-draft) paths can be tested."""
    from helpers import write_yaml

    library = tmp_path / "library"
    write_yaml(library, "arithmetic/published.yaml", published_record())
    report = load_knowledge(library)
    assert report.ok, [str(issue) for issue in report.errors]
    return KnowledgeStore.open(build_index(report, tmp_path / "data" / "knowledge.sqlite").index_path)
