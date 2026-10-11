"""Retrieval quality tests.

These check that the right concept comes back, that similar concepts are reported as ambiguous,
that missing material is reported as missing, and that unreviewed drafts stay hidden.
"""

from __future__ import annotations

import pytest

from mathengine.knowledge.retrieval import ContextBuilder, Retriever
from mathengine.errors import NotFoundError
from mathengine.knowledge.store import KnowledgeStore

FACTS = "arithmetic.multiplication.facts"
REPEATED = "arithmetic.multiplication.repeated-addition"
POWER_RULE = "calculus.derivatives.power-rule"
EXPONENTS = "algebra.exponents.laws"
LINEAR = "algebra.equations.linear-one-variable"


@pytest.fixture
def retriever(store: KnowledgeStore) -> Retriever:
    return Retriever(store)


def _top(result) -> str:
    assert result.hits, f"no hits for query; status={result.status}"
    return result.hits[0].concept_id


# --- exact and near-exact matches -----------------------------------------------------------

@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("times tables", FACTS),  # alias
        ("power rule", POWER_RULE),  # alias
        ("repeated addition", REPEATED),  # alias
        ("solve for x", LINEAR),  # alias with a stopword
        ("multiplication facts", FACTS),  # exact title
        ("linear equation", LINEAR),  # alias
    ],
)
def test_exact_titles_and_aliases_are_found_first(retriever, query, expected_id):
    result = retriever.search(query, include_drafts=True)
    assert result.status == "matches"
    assert _top(result) == expected_id
    assert result.hits[0].exact_match


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("Explain derivatives.", POWER_RULE),  # intent word stripped, plural stemmed
        ("Give me calculus problems.", POWER_RULE),  # subject word
        ("derivative of x^n", POWER_RULE),  # symbols ignored, keyword matched
        ("exponents", EXPONENTS),  # plural
        ("product of powers", EXPONENTS),  # phrase words in the formula area
        ("times 6", FACTS),  # number inside a topic phrase
    ],
)
def test_natural_language_requests_find_the_right_concept(retriever, query, expected_id):
    result = retriever.search(query, include_drafts=True)
    assert result.status in ("matches", "ambiguous")
    assert expected_id in [hit.concept_id for hit in result.hits[:2]]
    assert _top(result) == expected_id


# --- similar concepts and ambiguity ----------------------------------------------------------

def test_similar_concepts_are_reported_as_ambiguous_not_guessed(retriever):
    result = retriever.search("multiplication", include_drafts=True)
    assert result.status == "ambiguous"
    returned = {hit.concept_id for hit in result.hits}
    assert returned == {FACTS, REPEATED}
    assert "Which one did you mean" in result.message


def test_clear_request_is_not_ambiguous_even_with_a_similar_concept(retriever):
    result = retriever.search("multiplication facts", include_drafts=True)
    assert result.status == "matches"


# --- honest 'nothing trustworthy here' answers ------------------------------------------------

@pytest.mark.parametrize("query", ["Teach me fractions.", "quadratic formula", "sin cos", "pizza"])
def test_missing_material_is_reported_as_insufficient(retriever, query):
    result = retriever.search(query, include_drafts=True)
    assert result.status == "insufficient"
    assert result.hits == ()
    assert "No reviewed material matches" in result.message


@pytest.mark.parametrize("query", ["I don't understand why my answer is wrong", "", "   ", "please help me"])
def test_requests_without_a_topic_ask_for_clarification(retriever, query):
    result = retriever.search(query, include_drafts=True)
    assert result.status == "needs_clarification"
    assert result.hits == ()


def test_a_single_body_text_word_alone_is_not_enough_to_match(retriever):
    # "digit" appears only in the body text of the multiplication facts definition.
    assert retriever.search("digit", include_drafts=True).status == "insufficient"


def test_subject_filter_excludes_other_subjects(retriever):
    assert retriever.search("power", subject="arithmetic", include_drafts=True).status == "insufficient"
    assert _top(retriever.search("power", subject="calculus", include_drafts=True)) == POWER_RULE


# --- trust gate ------------------------------------------------------------------------------

def test_authoritative_search_gives_no_hint_that_drafts_exist(authoritative_store):
    result = Retriever(authoritative_store).search("power rule")
    assert result.status == "insufficient"
    assert result.hits == ()
    assert "draft" not in result.message.lower()


def test_authoritative_store_cannot_fetch_drafts_even_when_asked(authoritative_store):
    with pytest.raises(NotFoundError, match="No concept"):
        authoritative_store.get(POWER_RULE, include_drafts=True)


def test_drafts_can_be_requested_explicitly_for_development(retriever):
    assert _top(retriever.search("power rule", include_drafts=True)) == POWER_RULE


def test_preview_store_hides_drafts_unless_asked(store):
    with pytest.raises(NotFoundError, match="unreviewed AI draft"):
        store.get(POWER_RULE)
    assert store.get(POWER_RULE, include_drafts=True).title == "Power rule for derivatives"


# --- relationships and context ---------------------------------------------------------------

def test_prerequisite_chain_is_ordered_foundations_first(store):
    assert store.prerequisite_closure(POWER_RULE) == [REPEATED, FACTS, EXPONENTS]


def test_related_concepts_are_listed(store):
    assert POWER_RULE in store.direct_related(EXPONENTS)


def test_context_is_small_and_respects_its_budget(store):
    bundle = ContextBuilder(store).build(POWER_RULE, max_chars=400, include_drafts=True)
    assert len(bundle.text) <= 400
    assert bundle.truncated
    assert bundle.text.startswith(f"[{POWER_RULE} v0.1.0 · ai_draft]")


def test_context_never_contains_exercise_answers_or_hints(tmp_path):
    from helpers import record, write_yaml

    from mathengine.knowledge.index import build_index
    from mathengine.knowledge.loader import load_knowledge

    # Unusual numbers make accidental matches with other text very unlikely.
    secret_answer = "424242"
    secret_hint = "Hint mentioning the secret 515151"
    exercise = {
        "id": "secret-question",
        "prompt": "What is the product of the secret factors?",
        "answer_type": "number",
        "check": {"method": "exact_numeric", "expected": secret_answer},
        "hints": [secret_hint],
    }
    write_yaml(tmp_path / "knowledge", "arithmetic/sample.yaml", record(exercises=[exercise]))
    report = load_knowledge(tmp_path / "knowledge")
    assert report.ok, [str(issue) for issue in report.errors]
    index_path = build_index(report, tmp_path / "data" / "knowledge-dev.sqlite", include_drafts=True).index_path
    store = KnowledgeStore.open(index_path, expect_drafts=True)

    context = ContextBuilder(store).build("arithmetic.testing.sample", include_drafts=True).text
    assert secret_answer not in context
    assert "515151" not in context
