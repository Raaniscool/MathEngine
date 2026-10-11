"""Build the generated SQLite knowledge index.

The index is DERIVED data: it can always be rebuilt from the YAML records in knowledge/.
It never contains user progress. That lives in a separate database (see learning/progress.py),
so rebuilding the index cannot erase anybody's work.

Two indexes are built from the same library:

* The AUTHORITATIVE index (knowledge.sqlite) contains reviewed and verified records only.
  Unverified AI drafts never enter it. Everything students see comes from this file.
* The DEVELOPER PREVIEW index (knowledge-dev.sqlite) contains every record, including drafts.
  It is opened only when a request explicitly asks for drafts (developer mode). It is never used
  for normal retrieval, checks, or the assistant.

Build safety:
* Refuses to build when the library has validation errors.
* The authoritative build refuses when a reviewed record links to an unreviewed draft, because the
  student-facing index would then point at content it does not contain.
* Writes to a temporary file and atomically replaces the old index only after success.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .loader import LoadedRecord, LoadReport
from .models import SCHEMA_VERSION
from .text import phrase_key, tokens

INDEX_FORMAT_VERSION = 3  # 3: normalized synonyms and machine_checked tier; 2: drafts excluded from authoritative index
DRAFT_CONTENT_EXCLUDED = "excluded"
DRAFT_CONTENT_INCLUDED = "included"

# How strongly a term match counts, per field. Titles and aliases are the most trustworthy signals.
FIELD_TITLE = "title"
FIELD_ALIAS = "alias"
FIELD_KEYWORD = "keyword"
FIELD_TOPIC = "topic"  # covers subject, topic and subtopic
FIELD_BODY = "body"  # summary and definition text

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE concepts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    subtopic TEXT,
    difficulty INTEGER NOT NULL,
    summary TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    is_draft INTEGER NOT NULL,
    version TEXT NOT NULL,
    source_file TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX idx_concepts_subject ON concepts(subject);
CREATE TABLE concept_links (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('prerequisite', 'related'))
);
CREATE INDEX idx_concept_links_from ON concept_links(from_id);
CREATE TABLE concept_terms (
    term TEXT NOT NULL,
    concept_id TEXT NOT NULL,
    field TEXT NOT NULL
);
CREATE INDEX idx_concept_terms_term ON concept_terms(term);
CREATE TABLE concept_phrases (
    phrase TEXT NOT NULL,
    concept_id TEXT NOT NULL,
    field TEXT NOT NULL
);
CREATE INDEX idx_concept_phrases_phrase ON concept_phrases(phrase);
"""


class IndexBuildError(RuntimeError):
    """Raised when the library is invalid, so no index is written."""


@dataclass(frozen=True)
class IndexStats:
    index_path: Path
    concept_count: int  # concepts written to this file
    draft_count: int  # drafts written to this file (always 0 for the authoritative index)
    excluded_draft_count: int  # drafts left out of this file
    term_count: int


def build_index(report: LoadReport, index_path: Path, *, include_drafts: bool = False) -> IndexStats:
    """Write one index file. Use include_drafts=True only for the developer preview index."""
    if not report.ok:
        raise IndexBuildError(
            f"the knowledge library has {len(report.errors)} validation error(s); the index was not rebuilt"
        )

    drafts = [record for record in report.records if _is_draft(record)]
    if include_drafts:
        records = list(report.records)
    else:
        _reject_reviewed_links_to_drafts(report)
        records = [record for record in report.records if not _is_draft(record)]

    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_name(index_path.name + ".building")
    temp_path.unlink(missing_ok=True)

    connection = sqlite3.connect(temp_path)
    try:
        connection.executescript(_SCHEMA)
        draft_count, term_count = _insert_records(connection, records)
        built_at = datetime.now(UTC).isoformat(timespec="seconds")
        connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("format_version", str(INDEX_FORMAT_VERSION)),
                ("schema_version", str(SCHEMA_VERSION)),
                ("built_at", built_at),
                ("draft_content", DRAFT_CONTENT_INCLUDED if include_drafts else DRAFT_CONTENT_EXCLUDED),
                ("concept_count", str(len(records))),
                ("draft_count", str(draft_count)),
                ("excluded_draft_count", str(0 if include_drafts else len(drafts))),
                ("source_fingerprint", report.fingerprint),
            ],
        )
        connection.commit()
    except Exception:
        connection.close()
        temp_path.unlink(missing_ok=True)
        raise
    connection.close()

    os.replace(temp_path, index_path)  # atomic replacement of the previous index
    return IndexStats(
        index_path,
        concept_count=len(records),
        draft_count=draft_count,
        excluded_draft_count=0 if include_drafts else len(drafts),
        term_count=term_count,
    )


def _is_draft(record: LoadedRecord) -> bool:
    return record.concept.verification.status == "ai_draft"


def _reject_reviewed_links_to_drafts(report: LoadReport) -> None:
    drafts = {record.concept.id for record in report.records if _is_draft(record)}
    problems = []
    for record in report.records:
        if _is_draft(record):
            continue
        for target in (*record.concept.prerequisites, *record.concept.related):
            if target in drafts:
                problems.append(f"{record.concept.id} links to unreviewed draft {target}")
    if problems:
        raise IndexBuildError(
            "reviewed content links to unreviewed drafts; review the drafts or remove the links: "
            + "; ".join(problems)
        )


def _insert_records(connection: sqlite3.Connection, records: list[LoadedRecord]) -> tuple[int, int]:
    draft_count = 0
    term_rows: set[tuple[str, str, str]] = set()
    phrase_rows: set[tuple[str, str, str]] = set()

    for record in records:
        concept = record.concept
        is_draft = _is_draft(record)
        draft_count += int(is_draft)
        connection.execute(
            "INSERT INTO concepts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                concept.id,
                concept.title,
                concept.subject,
                concept.topic,
                concept.subtopic,
                concept.difficulty,
                concept.summary,
                concept.verification.status,
                int(is_draft),
                concept.version,
                record.relative_path,
                json.dumps(concept.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        connection.executemany(
            "INSERT INTO concept_links VALUES (?, ?, ?)",
            [(concept.id, target, "prerequisite") for target in concept.prerequisites]
            + [(concept.id, target, "related") for target in concept.related],
        )

        for term in tokens(concept.title):
            term_rows.add((term, concept.id, FIELD_TITLE))
        phrase_rows.add((phrase_key(concept.title), concept.id, FIELD_TITLE))
        for alias in concept.aliases:
            for term in tokens(alias):
                term_rows.add((term, concept.id, FIELD_ALIAS))
            phrase_rows.add((phrase_key(alias), concept.id, FIELD_ALIAS))
        for keyword in concept.keywords:
            for term in tokens(keyword):
                term_rows.add((term, concept.id, FIELD_KEYWORD))
        for label in (concept.subject, concept.topic, concept.subtopic or ""):
            for term in tokens(label):
                term_rows.add((term, concept.id, FIELD_TOPIC))
        for text in (concept.summary, concept.definition):
            for term in tokens(text):
                term_rows.add((term, concept.id, FIELD_BODY))

    connection.executemany("INSERT INTO concept_terms VALUES (?, ?, ?)", sorted(term_rows))
    connection.executemany("INSERT INTO concept_phrases VALUES (?, ?, ?)", sorted(phrase_rows))
    return draft_count, len(term_rows)
