"""Runtime settings. Each value can be overridden with an environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    knowledge_dir: Path  # version-controlled source records
    data_dir: Path  # generated and user data; never committed

    ollama_url: str
    ollama_model: str
    ollama_timeout_seconds: float = 120.0  # how long one assistant request may wait for the model

    @property
    def index_path(self) -> Path:
        """Authoritative, generated knowledge index. Reviewed and verified records only."""
        return self.data_dir / "generated" / "knowledge.sqlite"

    @property
    def dev_index_path(self) -> Path:
        """Developer preview index with unreviewed drafts. Never used unless a request asks for drafts."""
        return self.data_dir / "generated" / "knowledge-dev.sqlite"

    @property
    def progress_path(self) -> Path:
        """User progress. Kept separate so that index rebuilds can never delete it."""
        return self.data_dir / "user" / "progress.sqlite"


def _positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def load_settings() -> Settings:
    return Settings(
        knowledge_dir=Path(os.environ.get("MATHENGINE_KNOWLEDGE_DIR", REPO_ROOT / "knowledge")),
        data_dir=Path(os.environ.get("MATHENGINE_DATA_DIR", REPO_ROOT / "data")),
        ollama_url=os.environ.get("MATHENGINE_OLLAMA_URL", "http://127.0.0.1:11434"),
        # Starting point only. Benchmark small models on real assistant tasks before committing to one.
        ollama_model=os.environ.get("MATHENGINE_OLLAMA_MODEL", "qwen2.5:1.5b"),
        ollama_timeout_seconds=_positive_float(os.environ.get("MATHENGINE_OLLAMA_TIMEOUT"), 120.0),
    )
