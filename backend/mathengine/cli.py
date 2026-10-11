"""Command-line tools for the knowledge library.

    python -m mathengine.cli validate        # check every record; exit code 1 if anything is wrong
    python -m mathengine.cli build-index     # validate, then rebuild data/generated/knowledge.sqlite

build-index never touches user progress and never replaces the old index unless validation passes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_settings
from .knowledge.index import IndexBuildError, build_index
from .knowledge.loader import load_knowledge


def main(argv: list[str] | None = None) -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(prog="mathengine.cli", description=__doc__.splitlines()[0])
    parser.add_argument("--knowledge-dir", type=Path, default=settings.knowledge_dir)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate all knowledge records")
    commands.add_parser("build-index", help="validate, then rebuild the generated index")
    args = parser.parse_args(argv)

    report = load_knowledge(args.knowledge_dir)
    print(f"Checked {len(report.records)} valid record(s) in {args.knowledge_dir}")
    for issue in report.errors:
        print(f"  ERROR {issue}")

    if args.command == "validate":
        print("Validation passed." if report.ok else f"Validation FAILED with {len(report.errors)} error(s).")
        return 0 if report.ok else 1

    index_path = args.data_dir / "generated" / "knowledge.sqlite"
    try:
        stats = build_index(report, index_path)
    except IndexBuildError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(
        f"Index built: {stats.concept_count} concept(s) "
        f"({stats.draft_count} unreviewed draft(s) hidden by default), {stats.term_count} term row(s)."
    )
    print(f"Written to {stats.index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
