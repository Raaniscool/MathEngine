"""Index lifecycle tests: the index is rebuildable, missing indexes give clear errors, and progress survives rebuilds."""

from __future__ import annotations

import pytest

from mathengine.errors import IndexNotBuiltError
from mathengine.knowledge.index import IndexBuildError, build_index
from mathengine.knowledge.loader import load_knowledge
from mathengine.knowledge.store import KnowledgeStore
from mathengine.learning.progress import ProgressStore
from mathengine.learning.service import ExerciseService


def test_store_reports_counts_and_subjects(store):
    assert store.draft_count == 31
    assert store.concept_count == 0  # no record is approved for the default library yet
    counts = dict(store.subject_counts(include_drafts=True))
    assert counts["arithmetic"] == 23
    assert counts["algebra"] == 5
    assert counts["calculus"] == 1
    assert counts["geometry"] == 2
    assert counts["physics"] == 0


def test_store_returns_draft_records_only_when_asked(store):
    visible = {concept.id for concept in store.all_concepts()}
    assert "algebra.exponents.laws" not in visible
    assert len(store.all_concepts(include_drafts=True)) == 31


def test_authoritative_index_holds_reviewed_content_only(authoritative_store):
    assert authoritative_store.draft_count == 0
    assert authoritative_store.concept_count == 0
    assert authoritative_store.meta["excluded_draft_count"] == "31"
    assert authoritative_store.meta["draft_content"] == "excluded"


def test_preview_index_is_refused_as_authoritative_and_vice_versa(built_index, dev_index):
    with pytest.raises(IndexNotBuiltError, match="not the authoritative index"):
        KnowledgeStore.open(dev_index)
    with pytest.raises(IndexNotBuiltError, match="not the developer preview index"):
        KnowledgeStore.open(built_index, expect_drafts=True)


def test_reviewed_record_linking_to_a_draft_is_rejected(tmp_path):
    from helpers import published_record, record, write_yaml

    library = tmp_path / "library"
    write_yaml(library, "arithmetic/draft.yaml", record(id="arithmetic.testing.draft"))
    write_yaml(
        library,
        "arithmetic/published.yaml",
        {**published_record(), "related": ["arithmetic.testing.draft"]},
    )
    report = load_knowledge(library)
    assert report.ok, [str(issue) for issue in report.errors]
    with pytest.raises(IndexBuildError, match="links to unreviewed draft arithmetic.testing.draft"):
        build_index(report, tmp_path / "data" / "knowledge.sqlite")
    # The developer preview may still include both, because it is never used for students.
    build_index(report, tmp_path / "data" / "knowledge-dev.sqlite", include_drafts=True)


def test_missing_index_gives_an_actionable_error(tmp_path):
    with pytest.raises(IndexNotBuiltError, match="build-index"):
        KnowledgeStore.open(tmp_path / "nope.sqlite")


def test_index_rebuild_is_deterministic_and_fingerprinted(knowledge_dir, tmp_path):
    first = build_index(load_knowledge(knowledge_dir), tmp_path / "a.sqlite", include_drafts=True)
    second = build_index(load_knowledge(knowledge_dir), tmp_path / "b.sqlite", include_drafts=True)
    assert first.concept_count == second.concept_count == 31
    first_store = KnowledgeStore.open(first.index_path, expect_drafts=True)
    second_store = KnowledgeStore.open(second.index_path, expect_drafts=True)
    assert first_store.meta["source_fingerprint"] == second_store.meta["source_fingerprint"]


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
