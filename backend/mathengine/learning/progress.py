"""User progress storage.

This database lives in data/user/ and is NEVER deleted or rebuilt by the knowledge indexer.
Attempts refer to concepts and exercises by their stable string ids. Those ids survive index
rebuilds, so progress keeps pointing at the right lessons after the library is updated.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROGRESS_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    exercise_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    verified INTEGER NOT NULL,
    method TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_concept ON attempts(concept_id);
"""


class ProgressStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {PROGRESS_SCHEMA_VERSION}")

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        # Opened per call and closed afterwards, so no file handle stays open between requests.
        return _ClosingConnection(self._path)

    def record_attempt(
        self, concept_id: str, exercise_id: str, verdict: str, verified: bool, method: str
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO attempts (concept_id, exercise_id, verdict, verified, method, submitted_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    concept_id,
                    exercise_id,
                    verdict,
                    int(verified),
                    method,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            return int(cursor.lastrowid or 0)

    def attempts(self, concept_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, concept_id, exercise_id, verdict, verified, method, submitted_at FROM attempts"
        params: tuple[str, ...] = ()
        if concept_id is not None:
            query += " WHERE concept_id = ?"
            params = (concept_id,)
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY id", params).fetchall()
        columns = ("id", "concept_id", "exercise_id", "verdict", "verified", "method", "submitted_at")
        return [dict(zip(columns, row, strict=True)) | {"verified": bool(row[4])} for row in rows]

    def summary(self) -> dict[str, dict[str, int]]:
        """Per-concept counts: how many answers were attempted and how many were correct."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT concept_id, COUNT(*), SUM(verdict = 'correct') FROM attempts GROUP BY concept_id"
            ).fetchall()
        return {concept_id: {"attempts": total, "correct": int(correct or 0)} for concept_id, total, correct in rows}


class _ClosingConnection:
    """Context manager that commits on success and always closes the connection."""

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path)

    def __enter__(self) -> sqlite3.Connection:
        return self._connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
