"""Index lifecycle tests: the index is rebuildable, missing indexes give clear errors, and progress survives rebuilds."""

from __future__ import annotations

import pytest

from mathengine.errors import IndexNotBuiltError
from mathengine.knowledge.index import build_index
from mathengine.knowledge.loader import load_knowledge
from mathengine.knowledge.store import KnowledgeStore
from mathengine.learning.progress import ProgressStore
from mathengine.learning.service import ExerciseService


def test_store_reports_counts_and_subjects(store):
    assert store.draft_count == 5
    assert store.concept_count == 0  # every seed record is an unreviewed draft, so none are published
    counts = dict(store.subject_counts(include_drafts=True))
    assert counts["arithmetic"] == 2
    assert counts["algebra"] == 2
    assert counts["calculus"] == 1
    assert counts["physics"] == 0


def test_store_returns_draft_records_only_when_asked(store):
    assert store.all_concepts() == []
    assert len(store.all_concepts(include_drafts=True)) == 5


def test_missing_index_gives_an_actionable_error(tmp_path):
    with pytest.raises(IndexNotBuiltError, match="build-index"):
        KnowledgeStore.open(tmp_path / "nope.sqlite")


def test_index_rebuild_is_deterministic_and_fingerprinted(knowledge_dir, tmp_path):
    first = build_index(load_knowledge(knowledge_dir), tmp_path / "a.sqlite")
    second = build_index(load_knowledge(knowledge_dir), tmp_path / "b.sqlite")
    assert first.concept_count == second.concept_count == 5
    assert KnowledgeStore.open(first.index_path).meta["source_fingerprint"] == KnowledgeStore.open(second.index_path).meta["source_fingerprint"]


def test_progress_survives_an_index_rebuild(knowledge_dir, data_dir):
    index_path = build_index(load_knowledge(knowledge_dir), data_dir / "generated" / "knowledge.sqlite").index_path
    progress = ProgressStore(data_dir / "user" / "progress.sqlite")
    progress.record_attempt("arithmetic.multiplication.facts", "seven-times-eight", "correct", True, "exact_numeric")

    # Simulate a library update: delete the generated index and rebuild it from source.
    index_path.unlink()
    build_index(load_knowledge(knowledge_dir), index_path)

    attempts = ProgressStore(data_dir / "user" / "progress.sqlite").attempts("arithmetic.multiplication.facts")
    assert len(attempts) == 1
    assert attempts[0]["verdict"] == "correct"
    assert attempts[0]["verified"] is True


def test_progress_summary_counts_correct_answers(data_dir):
    progress = ProgressStore(data_dir / "user" / "progress.sqlite")
    progress.record_attempt("arithmetic.multiplication.facts", "a", "correct", True, "exact_numeric")
    progress.record_attempt("arithmetic.multiplication.facts", "a", "incorrect", True, "exact_numeric")
    assert progress.summary() == {"arithmetic.multiplication.facts": {"attempts": 2, "correct": 1}}


def test_exercise_service_records_attempts_and_returns_feedback(store, data_dir):
    progress = ProgressStore(data_dir / "user" / "progress.sqlite")
    service = ExerciseService(store, progress)
    outcome = service.check("arithmetic.multiplication.facts", "seven-times-eight", "56", include_drafts=True)
    assert outcome.verdict.value == "correct"
    assert outcome.verified is True
    assert outcome.feedback == "Correct. 7 x 8 = 56."
    assert outcome.attempt_id >= 1

    wrong = service.check("arithmetic.multiplication.facts", "seven-times-eight", "54", include_drafts=True)
    assert wrong.verdict.value == "incorrect"
    assert wrong.feedback == "Try splitting one factor into two easier parts."


def test_hint_service_respects_the_hint_range(store, data_dir):
    service = ExerciseService(store, ProgressStore(data_dir / "user" / "progress.sqlite"))
    first = service.hint("arithmetic.multiplication.facts", "seven-times-eight", 0, include_drafts=True)
    assert first.has_more
    with pytest.raises(Exception, match="does not exist"):
        service.hint("arithmetic.multiplication.facts", "seven-times-eight", 5, include_drafts=True)
