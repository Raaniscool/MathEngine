"""Retrieval: find trusted knowledge for a free-text request.

How a query is scored (see MATHENGINE_PROJECT_CONTEXT.md §6):
* The query is normalized and tokenized the same way the index was built (text.py), including
  synonyms, so "times tables", "multiplication facts" and "7 times 8" share vocabulary with records.
* Each query term is weighted by IDF: a term that appears in few records ("fraction") counts for
  more than one that appears in many ("number"). Unknown words are not guessed at, except for
  close typos of words of 5+ letters.
* Where a term matched matters: title > alias > keyword > topic > body text.
* A concept qualifies only if (a) the whole normalized query is an exact title or alias, or
  (b) it matches enough query terms (at least 60% of them, and at least one that is not generic)
  through a title, alias, keyword or topic field. Body-text matches alone never qualify.
* Outcomes, never a silent guess:
    matches             - one concept clearly fits, or the query names an exact title or alias
    ambiguous           - several concepts fit about equally; up to 3 options are offered
    insufficient        - nothing fits; nearby topics are suggested when any exist
    needs_clarification - the request contains no topic words (for example "I don't understand")
* Developer mode (include_diagnostics=True) also returns the terms used, their IDF weights, and
  the candidates that were rejected, with the reason.
"""

from __future__ import annotations

import difflib
import math
from collections import defaultdict
from dataclasses import dataclass, field

from .index import FIELD_ALIAS, FIELD_BODY, FIELD_KEYWORD, FIELD_TITLE, FIELD_TOPIC
from .models import Concept
from .store import KnowledgeStore
from .text import INTENT_WORDS, normalize, phrase_key, term_pairs, tokens, typo_lexicon

FIELD_WEIGHTS = {
    FIELD_TITLE: 10,
    FIELD_ALIAS: 8,
    FIELD_KEYWORD: 6,
    FIELD_TOPIC: 6,
    FIELD_BODY: 2,
}
EXACT_PHRASE_BONUS = 100.0
COVERAGE_SHARE = 0.6  # a concept must match at least this share of the query terms (rounded up)
GENERIC_SHARE = 0.5  # with a large library, a term in more than this share of records is "generic"
MIN_CORPUS_FOR_SHARE = 20  # the share rule is meaningless with only a handful of records
# Words that name no topic even when they appear in titles ("number line" is still found by "line").
GENERIC_TERMS = frozenset(
    {"number", "math", "mathematics", "problem", "method", "way", "thing", "value", "example", "rule"}
)
# A term that appears in several fields of the same record is stronger evidence than one field alone.
# The best field counts in full; each other matching field adds this share of its weight.
EXTRA_FIELD_SHARE = 0.3
FUZZY_MIN_LENGTH = 5  # typo matching only for words of this length or longer
FUZZY_CUTOFF = 0.85
AMBIGUITY_RATIO = 0.75  # a runner-up within 75% of the best score makes the question ambiguous
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_OPTIONS = 3  # clarifying questions never offer more than this
BROAD_MIN_HITS = 3  # a non-exact request that fits this many records is ambiguous
MAX_SUGGESTIONS = 3


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
    coverage: float = 0.0


@dataclass(frozen=True)
class TermInfo:
    term: str  # the normalized term that was searched for
    concept_count: int  # how many visible records contain it
    idf: float
    fuzzy_for: str | None = None  # the typed word, when the term came from a typo match


@dataclass(frozen=True)
class Rejection:
    concept_id: str
    score: float
    coverage: float
    reason: str


@dataclass(frozen=True)
class SearchResult:
    query: str
    status: str  # matches | ambiguous | insufficient | needs_clarification
    message: str
    hits: tuple[SearchHit, ...] = ()
    options: tuple[SearchHit, ...] = ()  # for "ambiguous": at most MAX_OPTIONS choices
    suggestions: tuple[SearchHit, ...] = ()  # for "insufficient": nearby topics, if any
    terms: tuple[TermInfo, ...] = ()
    diagnostics: dict[str, object] = field(default_factory=dict)  # developer mode only


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
        include_diagnostics: bool = False,
    ) -> SearchResult:
        limit = max(1, min(limit, MAX_LIMIT))
        pairs = term_pairs(query)
        exact_keys = _exact_keys(query)
        has_exact_phrase = any(self._store.phrase_hits(key) for key in exact_keys)
        if not pairs and not has_exact_phrase:
            return SearchResult(
                query,
                "needs_clarification",
                "Which topic would you like to work on? Try a concept name such as "
                "'multiplication facts', 'long division' or 'fractions'.",
            )

        visible_ids = [concept.id for concept in self._store.all_concepts(include_drafts=include_drafts)]
        corpus_size = max(1, len(visible_ids))
        visible = set(visible_ids)
        terms, term_hits = self._resolve_terms(pairs, visible, corpus_size)

        hits, rejections = self._score(query, terms, term_hits, visible, subject, include_drafts)
        diagnostics: dict[str, object] = {}
        if include_diagnostics:
            diagnostics = {
                "normalized_terms": [info.term for info in terms],
                "corpus_size": corpus_size,
                "drafts_hidden": (0 if include_drafts else self._store.draft_count),
                "accepted": [hit.concept_id for hit in hits[:limit]],
                "rejected": [
                    {"concept_id": r.concept_id, "score": round(r.score, 2), "coverage": round(r.coverage, 2), "reason": r.reason}
                    for r in rejections[:15]
                ],
            }

        if not hits:
            suggestions = self._nearby(terms, term_hits, visible, subject, include_drafts)
            if suggestions:
                names = ", ".join(f"'{hit.title}'" for hit in suggestions)
                message = (
                    f"No reviewed material matches '{query.strip()}'. Nearby topics that exist: {names}."
                )
            else:
                message = f"No reviewed material matches '{query.strip()}' yet."
            return SearchResult(query, "insufficient", message, (), (), tuple(suggestions), tuple(terms), diagnostics)

        best = hits[0]
        if best.exact_match:
            return SearchResult(
                query, "matches", "Exact match found.", tuple(hits[:limit]), (), (), tuple(terms), diagnostics
            )
        close = tuple(hit for hit in hits if hit.score >= AMBIGUITY_RATIO * best.score)
        # A broad request (no exact title or alias) that fits several records is a question, not a guess.
        broad = len(hits) >= BROAD_MIN_HITS
        if len(close) > 1 or broad:
            options = (close if len(close) > 1 else tuple(hits))[:MAX_OPTIONS]
            names = [f"'{hit.title}'" for hit in options]
            more = max(len(close), len(hits)) - len(options) if broad and len(close) <= 1 else len(close) - len(options)
            listed = ", ".join(names) + (f", or {more} more" if more else "")
            return SearchResult(
                query,
                "ambiguous",
                f"Several topics match. Which one did you mean: {listed}?",
                tuple(hits[:limit]),
                tuple(options),
                (),
                tuple(terms),
                diagnostics,
            )
        return SearchResult(query, "matches", "Matching concept found.", tuple(hits[:limit]), (), (), tuple(terms), diagnostics)

    # --- term resolution ----------------------------------------------------------------

    def _resolve_terms(
        self, pairs: list[tuple[str, str]], visible: set[str], corpus_size: int
    ) -> tuple[list[TermInfo], dict[str, list[tuple[str, str]]]]:
        """Return the unique terms with their IDF weight, and per term the (concept_id, field) hits.

        A typed word of FUZZY_MIN_LENGTH+ letters that matches nothing is compared with the typo
        lexicon. The correction is used only when it matches at least one visible record.
        """
        lexicon: dict[str, str] | None = None
        infos: list[TermInfo] = []
        hits_by_term: dict[str, list[tuple[str, str]]] = {}
        for raw, term in pairs:
            if term in hits_by_term:
                continue
            hits = self._visible_hits(term, visible)
            fuzzy_for: str | None = None
            if not hits and len(raw) >= FUZZY_MIN_LENGTH:
                if lexicon is None:
                    lexicon = typo_lexicon(self._store.vocabulary())
                close = difflib.get_close_matches(raw, list(lexicon), n=1, cutoff=FUZZY_CUTOFF)
                if close and lexicon[close[0]] != term:
                    corrected = lexicon[close[0]]
                    corrected_hits = self._visible_hits(corrected, visible)
                    if corrected_hits:
                        term, hits, fuzzy_for = corrected, corrected_hits, raw
                        if term in hits_by_term:
                            continue
            # Document frequency uses title/alias/keyword/topic hits only. Body text mentions many
            # terms in passing, so it must not make a term look generic. A body-only term falls
            # back to its body frequency; it can never qualify a concept on its own anyway.
            informative_count = len({cid for cid, field_name in hits if field_name != FIELD_BODY})
            concept_count = informative_count or len({cid for cid, _ in hits})
            idf = math.log(1 + corpus_size / concept_count) if concept_count else 0.0
            infos.append(TermInfo(term, concept_count, round(idf, 4), fuzzy_for))
            hits_by_term[term] = hits
        return infos, hits_by_term

    @staticmethod
    def _is_generic(term: str, concept_count: int, corpus_size: int) -> bool:
        if term in GENERIC_TERMS:
            return True
        return corpus_size >= MIN_CORPUS_FOR_SHARE and concept_count / corpus_size > GENERIC_SHARE

    def _visible_hits(self, term: str, visible: set[str]) -> list[tuple[str, str]]:
        return [(h.concept_id, h.field) for h in self._store.term_hits(term) if h.concept_id in visible]

    # --- scoring ------------------------------------------------------------------------

    def _score(
        self,
        query: str,
        terms: list[TermInfo],
        term_hits: dict[str, list[tuple[str, str]]],
        visible: set[str],
        subject: str | None,
        include_drafts: bool,
    ) -> tuple[list[SearchHit], list[Rejection]]:
        term_count = max(1, len(terms))
        needed = max(1, math.ceil(COVERAGE_SHARE * term_count))

        score: dict[str, float] = defaultdict(float)
        matched: dict[str, set[str]] = defaultdict(set)  # any field, shown to the user
        strong_terms: dict[str, set[str]] = defaultdict(set)  # title/alias/keyword/topic, non-generic
        for info in terms:
            generic = self._is_generic(info.term, info.concept_count, max(1, len(visible)))
            weights_per_concept: dict[str, list[int]] = defaultdict(list)
            for concept_id, field_name in term_hits.get(info.term, []):
                weights_per_concept[concept_id].append(FIELD_WEIGHTS[field_name])
                if field_name != FIELD_BODY and not generic:
                    strong_terms[concept_id].add(info.term)
            for concept_id, weights in weights_per_concept.items():
                best = max(weights)
                extra = sum(weights) - best
                matched[concept_id].add(info.term)
                score[concept_id] += (best + EXTRA_FIELD_SHARE * extra) * info.idf

        phrase_keys = _exact_keys(query)
        exact_ids: set[str] = set()
        for key in phrase_keys:
            exact_ids.update(h.concept_id for h in self._store.phrase_hits(key) if h.concept_id in visible)

        hits: list[SearchHit] = []
        rejections: list[Rejection] = []
        for concept_id in sorted(set(matched) | exact_ids):
            concept = self._store.get(concept_id, include_drafts=True)
            coverage = len(strong_terms.get(concept_id, ())) / term_count
            is_exact = concept_id in exact_ids
            if subject is not None and concept.subject != subject:
                rejections.append(Rejection(concept_id, score.get(concept_id, 0.0), coverage, "other subject"))
                continue
            if not is_exact:
                if not strong_terms.get(concept_id):
                    rejections.append(
                        Rejection(concept_id, score.get(concept_id, 0.0), coverage, "only generic terms or body text matched")
                    )
                    continue
                if len(strong_terms[concept_id]) < needed:
                    rejections.append(
                        Rejection(
                            concept_id,
                            score.get(concept_id, 0.0),
                            coverage,
                            f"matches {len(strong_terms[concept_id])} of {term_count} terms; needs {needed}",
                        )
                    )
                    continue
            total = score.get(concept_id, 0.0) + (EXACT_PHRASE_BONUS if is_exact else 0.0)
            hits.append(
                SearchHit(
                    concept_id=concept.id,
                    title=concept.title,
                    subject=concept.subject,
                    topic=concept.topic,
                    score=round(total, 4),
                    matched_terms=tuple(sorted(matched.get(concept_id, ()))),
                    exact_match=is_exact,
                    verification_status=concept.verification.status,
                    coverage=round(coverage, 4),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.concept_id))
        return hits, rejections

    def _nearby(
        self,
        terms: list[TermInfo],
        term_hits: dict[str, list[tuple[str, str]]],
        visible: set[str],
        subject: str | None,
        include_drafts: bool,
    ) -> list[SearchHit]:
        """Concepts that share at least one informative, non-generic term with the query."""
        corpus = max(1, len(visible))
        share: dict[str, int] = defaultdict(int)
        for info in terms:
            if self._is_generic(info.term, info.concept_count, corpus):
                continue
            for concept_id, field_name in term_hits.get(info.term, []):
                if field_name != FIELD_BODY:
                    share[concept_id] += 1
        suggestions: list[SearchHit] = []
        for concept_id, count in sorted(share.items(), key=lambda item: (-item[1], item[0])):
            concept = self._store.get(concept_id, include_drafts=True)
            if subject is not None and concept.subject != subject:
                continue
            suggestions.append(
                SearchHit(
                    concept_id=concept.id,
                    title=concept.title,
                    subject=concept.subject,
                    topic=concept.topic,
                    score=float(count),
                    matched_terms=(),
                    exact_match=False,
                    verification_status=concept.verification.status,
                )
            )
            if len(suggestions) == MAX_SUGGESTIONS:
                break
        return suggestions


def _exact_keys(query: str) -> set[str]:
    """Phrase keys that count as an exact title or alias: with and without the request words."""
    words = normalize(query).split()
    keys = {phrase_key(query)}
    content = [word for word in words if word not in INTENT_WORDS]
    if content:
        keys.add(phrase_key(" ".join(content)))
    keys.discard("")
    return keys


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
