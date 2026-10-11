"""Command-line tests for validating and building the knowledge index."""

from __future__ import annotations

from helpers import record, write_yaml

from mathengine.cli import main


def test_validate_passes_for_the_repository_library(knowledge_dir, data_dir, capsys):
    assert main(["--knowledge-dir", str(knowledge_dir), "--data-dir", str(data_dir), "validate"]) == 0
    assert "Validation passed." in capsys.readouterr().out


def test_build_index_writes_both_indexes(knowledge_dir, data_dir, capsys):
    assert main(["--knowledge-dir", str(knowledge_dir), "--data-dir", str(data_dir), "build-index"]) == 0
    assert (data_dir / "generated" / "knowledge.sqlite").is_file()
    assert (data_dir / "generated" / "knowledge-dev.sqlite").is_file()
    out = capsys.readouterr().out
    assert "0 reviewed concept(s), 5 unreviewed draft(s) excluded" in out
    assert "including 5 unreviewed draft(s)" in out


def test_build_index_fails_loudly_and_writes_nothing_for_bad_records(tmp_path, capsys):
    library = tmp_path / "library"
    write_yaml(library, "arithmetic/bad.yaml", record(titel="typo"))
    data = tmp_path / "data"
    assert main(["--knowledge-dir", str(library), "--data-dir", str(data), "build-index"]) == 1
    assert not (data / "generated" / "knowledge.sqlite").exists()
    assert not (data / "generated" / "knowledge-dev.sqlite").exists()
    assert "ERROR" in capsys.readouterr().out
