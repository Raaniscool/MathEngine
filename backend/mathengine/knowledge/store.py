"""Read-only access to the built knowledge index.

The index is opened once and loaded into memory. That keeps the database file closed while the
app runs, which matters on Windows: an index can only be replaced after its file handle is closed.
After a rebuild, call reload (or restart the backend) to pick up the new index.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..errors import IndexNotBuiltError, NotFoundError
from .models import SUBJECTS, Concept


@dataclass(frozen=True)
class TermHit:
    concept_id: str
    field: str


class KnowledgeStore:
    def __init__(
        self,
        concepts: dict[str, Concept],
        draft_ids: set[str],
        prerequisites: dict[str, list[str]],
        related: dict[str, list[str]],
        term_index: dict[str, list[TermHit]],
        phrase_index: dict[str, list[TermHit]],
        meta: dict[str, str],
    ) -> None:
        self._concepts = concepts
        self._draft_ids = draft_ids
        self._prerequisites = prerequisites
        self._related = related
        self._term_index = term_index
        self._phrase_index = phrase_index
        self.meta = meta

    @classmethod
    def open(cls, index_path: Path) -> KnowledgeStore:
        if not index_path.is_file():
            raise IndexNotBuiltError(
                f"The knowledge index was not found at {index_path}. "
                "Run: python -m mathengine.cli build-index"
            )
        uri = index_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))
            concepts: dict[str, Concept] = {}
            draft_ids: set[str] = set()
            for concept_id, is_draft, record_json in connection.execute(
                "SELECT id, is_draft, record_json FROM concepts"
            ):
                concepts[concept_id] = Concept.model_validate_json(record_json)
                if is_draft:
                    draft_ids.add(concept_id)

            prerequisites: dict[str, list[str]] = defaultdict(list)
            related: dict[str, list[str]] = defaultdict(list)
            for from_id, to_id, kind in connection.execute("SELECT from_id, to_id, kind FROM concept_links"):
                (prerequisites if kind == "prerequisite" else related)[from_id].append(to_id)

            term_index: dict[str, list[TermHit]] = defaultdict(list)
            for term, concept_id, field in connection.execute("SELECT term, concept_id, field FROM concept_terms"):
                term_index[term].append(TermHit(concept_id, field))

            phrase_index: dict[str, list[TermHit]] = defaultdict(list)
            for phrase, concept_id, field in connection.execute(
                "SELECT phrase, concept_id, field FROM concept_phrases"
            ):
                phrase_index[phrase].append(TermHit(concept_id, field))
        finally:
            connection.close()

        return cls(
            concepts=concepts,
            draft_ids=draft_ids,
            prerequisites=dict(prerequisites),
            related=dict(related),
            term_index=dict(term_index),
            phrase_index=dict(phrase_index),
            meta=meta,
        )

    # --- visibility -----------------------------------------------------------------------

    @property
    def concept_count(self) -> int:
        return len(self._concepts) - len(self._draft_ids)

    @property
    def draft_count(self) -> int:
        return len(self._draft_ids)

    def is_draft(self, concept_id: str) -> bool:
        return concept_id in self._draft_ids

    def is_visible(self, concept_id: str, include_drafts: bool = False) -> bool:
        return concept_id in self._concepts and (include_drafts or not self.is_draft(concept_id))

    # --- lookups --------------------------------------------------------------------------

    def get(self, concept_id: str, include_drafts: bool = False) -> Concept:
        if concept_id not in self._concepts:
            raise NotFoundError(f"No concept with id '{concept_id}'.")
        if self.is_draft(concept_id) and not include_drafts:
            raise NotFoundError(
                f"Concept '{concept_id}' is an unreviewed AI draft and is hidden from normal use."
            )
        return self._concepts[concept_id]

    def all_concepts(self, subject: str | None = None, include_drafts: bool = False) -> list[Concept]:
        return [
            concept
            for concept_id, concept in sorted(self._concepts.items())
            if (subject is None or concept.subject == subject)
            and self.is_visible(concept_id, include_drafts)
        ]

    def subject_counts(self, include_drafts: bool = False) -> list[tuple[str, int]]:
        counts = {subject: 0 for subject in SUBJECTS}
        for concept in self.all_concepts(include_drafts=include_drafts):
            counts[concept.subject] += 1
        return list(counts.items())

    def direct_prerequisites(self, concept_id: str) -> list[str]:
        return list(self._prerequisites.get(concept_id, []))

    def direct_related(self, concept_id: str) -> list[str]:
        return list(self._related.get(concept_id, []))

    def prerequisite_closure(self, concept_id: str) -> list[str]:
        """All transitive prerequisites, ordered so that each one comes after its own prerequisites."""
        ordered: list[str] = []
        seen: set[str] = set()

        def visit(current: str) -> None:
            for prerequisite in self._prerequisites.get(current, []):
                if prerequisite not in seen:
                    seen.add(prerequisite)
                    visit(prerequisite)
                    ordered.append(prerequisite)

        visit(concept_id)
        return ordered

    def term_hits(self, term: str) -> list[TermHit]:
        return self._term_index.get(term, [])

    def phrase_hits(self, phrase: str) -> list[TermHit]:
        return self._phrase_index.get(phrase, [])
