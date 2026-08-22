"""Tests for the reviewed source synchronization workflow."""

from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from fortran_mcp.source_cli import SourceSyncError, main, sync_sources
from fortran_mcp.sources import Source


def test_sync_source_runs_download_chunk_and_single_index_build(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    def ingest(source: Source, _data: Path) -> None:
        calls.append(("ingest", source.id))

    def build(source_id: str, _data: Path) -> tuple[object, object]:
        calls.append(("build", source_id))
        return object(), object()

    def index(_data: Path) -> int:
        calls.append(("index", "all"))
        return 42

    monkeypatch.setattr("fortran_mcp.source_cli.ingest_source", ingest)
    monkeypatch.setattr("fortran_mcp.source_cli.build_documents", build)
    monkeypatch.setattr("fortran_mcp.source_cli.build_index", index)

    report = sync_sources(["fpm-0.13.0-docs"], tmp_path)

    assert calls == [
        ("ingest", "fpm-0.13.0-docs"),
        ("build", "fpm-0.13.0-docs"),
        ("index", "all"),
    ]
    assert report.sources[0].downloaded is True
    assert report.sources[0].chunks == 2
    assert report.indexed_chunks == 42


def test_sync_source_reuses_existing_immutable_ingestion(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    records = tmp_path / "records"
    records.mkdir()
    (records / "fpm-0.13.0-docs.json").write_text("existing")
    monkeypatch.setattr(
        "fortran_mcp.source_cli.ingest_source",
        lambda *_args: (_ for _ in ()).throw(AssertionError("downloaded again")),
    )
    monkeypatch.setattr("fortran_mcp.source_cli.build_documents", lambda *_args: (object(),))
    monkeypatch.setattr("fortran_mcp.source_cli.build_index", lambda *_args: 1)

    report = sync_sources(["fpm-0.13.0-docs"], tmp_path)

    assert report.sources[0].downloaded is False
    assert report.sources[0].chunks == 1


def test_sync_validates_every_source_before_writing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fortran_mcp.source_cli.ingest_source",
        lambda *_args: (_ for _ in ()).throw(AssertionError("wrote before validation")),
    )

    with pytest.raises(SourceSyncError, match="unknown source IDs: missing"):
        sync_sources(["fpm-0.13.0-docs", "missing"], tmp_path)


def test_source_list_is_available_to_people_and_agents(capsys: CaptureFixture[str]) -> None:
    main(["list"])
    human = capsys.readouterr().out
    assert "fpm-0.13.0-docs" in human
    assert "MIT" in human
    assert "https://" in human
    assert "approved" not in human

    main(["list", "--json"])
    machine = capsys.readouterr().out
    assert '"schema_version": 1' in machine
    assert '"source_url"' in machine
    assert '"approved"' in machine
