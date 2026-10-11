"""Retrieval: find trusted knowledge for a free-text request.

Design choices (see MATHENGINE_PROJECT_CONTEXT.md):
* Structured and keyword-based only for now. Each term is looked up in the SQLite index, then
  candidates are scored by WHERE the term matched (title > alias > keyword > topic > body).
* Four outcomes, never a silent guess:
    matches             - one or more concepts clearly match
    ambiguous           - several concepts match about equally well; the caller should ask the user
    insufficient        - nothing trustworthy matches; the caller must say so
    needs_clarification - the request contains no topic words (for example "I don't understand")
* ContextBuilder gives the AI a small, size-limited slice of one concept. It never includes
  exercise answers, hints, or unreviewed drafts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .index import FIELD_ALIAS, FIELD_BODY, FIELD_KEYWORD, FIELD_TITLE, FIELD_TOPIC
from .models import Concept
from .store import KnowledgeStore
from .text import phrase_key, tokens

FIELD_WEIGHTS = {
    FIELD_TITLE: 10,
    FIELD_ALIAS: 8,
    FIELD_KEYWORD: 6,
    FIELD_TOPIC: 6,
    FIELD_BODY: 2,
}
EXACT_PHRASE_BONUS = 100
AMBIGUITY_RATIO = 0.75  # runner-up within 75% of the best score means "ambiguous"
DEFAULT_LIMIT = 5
MAX_LIMIT = 20


@dataclass(frozen=True)
class SearchHit:
    concept_id: str
    title: str
    subject: str
    topic: str
    score: float
    matched_terms: tuple[str, ...]
    exact_match: bool
    verification_status: str


@dataclass(frozen=True)
class SearchResult:
    query: str
    status: str  # matches | ambiguous | insufficient | needs_clarification
    message: str
    hits: tuple[SearchHit, ...] = ()


class Retriever:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        include_drafts: bool = False,
        limit: int = DEFAULT_LIMIT,
    ) -> SearchResult:
        limit = max(1, min(limit, MAX_LIMIT))
        if not tokens(query):
            return SearchResult(
                query,
                "needs_clarification",
                "Which topic would you like to work on? Try a concept name such as "
                "'multiplication facts' or 'power rule'.",
            )

        hits = self._rank(query, subject, include_drafts)
        if not hits:
            return SearchResult(query, "insufficient", f"No reviewed material matches '{query.strip()}'.")

        best = hits[0]
        if best.exact_match:
            return SearchResult(query, "matches", "Exact match found.", tuple(hits[:limit]))
        if len(hits) > 1 and hits[1].score >= AMBIGUITY_RATIO * best.score:
            close = tuple(hit for hit in hits if hit.score >= AMBIGUITY_RATIO * best.score)[:limit]
            titles = ", ".join(f"'{hit.title}'" for hit in close)
            return SearchResult(
                query,
                "ambiguous",
                f"Several concepts match. Which one did you mean: {titles}?",
                close,
            )
        return SearchResult(query, "matches", "Matching concepts found.", tuple(hits[:limit]))

    def _rank(self, query: str, subject: str | None, include_drafts: bool) -> list[SearchHit]:
        terms = list(dict.fromkeys(tokens(query)))  # unique, order kept
        best_weight: dict[str, dict[str, int]] = defaultdict(dict)  # concept -> term -> best weight
        strong: dict[str, bool] = defaultdict(bool)  # matched a title/alias/keyword/topic term
        body_terms: dict[str, set[str]] = defaultdict(set)

        for term in terms:
            for hit in self._store.term_hits(term):
                weight = FIELD_WEIGHTS[hit.field]
                if weight > best_weight[hit.concept_id].get(term, 0):
                    best_weight[hit.concept_id][term] = weight
                if hit.field == FIELD_BODY:
                    body_terms[hit.concept_id].add(term)
                else:
                    strong[hit.concept_id] = True

        key = phrase_key(query)
        exact_ids = {hit.concept_id for hit in self._store.phrase_hits(key)} if key else set()

        results: list[SearchHit] = []
        for concept_id in set(best_weight) | exact_ids:
            # A body-text match alone is too weak: require two different body terms.
            if not (strong[concept_id] or len(body_terms[concept_id]) >= 2):
                continue
            if not self._store.is_visible(concept_id, include_drafts):
                continue
            concept = self._store.get(concept_id, include_drafts=True)
            if subject is not None and concept.subject != subject:
                continue

            matched = best_weight.get(concept_id, {})
            score = float(sum(matched.values()))
            is_exact = concept_id in exact_ids
            if is_exact:
                score += EXACT_PHRASE_BONUS
            results.append(_hit(concept, score, tuple(sorted(matched)), is_exact))

        results.sort(key=lambda hit: (-hit.score, hit.concept_id))
        return results


def _hit(concept: Concept, score: float, matched: tuple[str, ...], exact: bool) -> SearchHit:
    return SearchHit(
        concept_id=concept.id,
        title=concept.title,
        subject=concept.subject,
        topic=concept.topic,
        score=score,
        matched_terms=matched,
        exact_match=exact,
        verification_status=concept.verification.status,
    )


@dataclass(frozen=True)
class ContextBundle:
    """A small, size-limited text block the AI may use to answer about one concept."""

    concept_id: str
    text: str
    included_sections: tuple[str, ...]
    truncated: bool
    sources: tuple[str, ...] = field(default_factory=tuple)


class ContextBuilder:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def build(self, concept_id: str, *, max_chars: int = 2000, include_drafts: bool = False) -> ContextBundle:
        concept = self._store.get(concept_id, include_drafts=include_drafts)
        sections: list[tuple[str, str]] = [
            ("Concept", f"{concept.title} ({concept.subject} > {concept.topic}, difficulty {concept.difficulty}/10)"),
            ("Summary", concept.summary),
            ("Definition", concept.definition),
        ]
        intro = next((item.text for item in concept.explanations if item.level == "intro"), None)
        if intro:
            sections.append(("Intuition", intro))
        for formula in concept.formulas:
            sections.append(("Formula", f"{formula.name}: {formula.expression}"))
        for example in concept.worked_examples[:1]:
            sections.append(("Worked example", f"{example.problem} Steps: {' '.join(example.steps)} Answer: {example.answer}"))
        for misconception in concept.misconceptions[:2]:
            sections.append(("Common mistake", f"{misconception.description} Correction: {misconception.correction}"))
        prerequisites = [self._title(item) for item in self._store.direct_prerequisites(concept_id)]
        if prerequisites:
            sections.append(("Prerequisites", ", ".join(prerequisites)))
        related = [self._title(item) for item in self._store.direct_related(concept_id)]
        if related:
            sections.append(("Related", ", ".join(related)))

        header = f"[{concept.id} v{concept.version} · {concept.verification.status}]"
        lines = [header]
        included: list[str] = []
        truncated = False
        used = len(header)
        for label, body in sections:
            line = f"{label}: {body}"
            if used + len(line) + 1 > max_chars:
                truncated = True
                break
            lines.append(line)
            included.append(label)
            used += len(line) + 1
        sources = tuple(source.title for source in concept.sources)
        return ContextBundle(concept.id, "\n".join(lines), tuple(included), truncated, sources)

    def _title(self, concept_id: str) -> str:
        if not self._store.is_visible(concept_id):
            return concept_id
        return self._store.get(concept_id).title
