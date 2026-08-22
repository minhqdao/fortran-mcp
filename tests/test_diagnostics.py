"""Tests for installation diagnostics."""

from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from fortran_mcp.diagnostics import diagnose, main

from .mcp_fixtures import prepare_index
from .test_data_cli import _installed_core


def test_doctor_reports_missing_data_without_prescribing_actions(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FORTRAN_MCP_SEARCH_PROVIDER", raising=False)

    report = diagnose()
    main([])

    output = capsys.readouterr().out
    assert report.search_provider == "lexical"
    assert "Data: none" in output
    assert "Ready:" not in output
    assert "Next:" not in output


def test_doctor_reports_invalid_provider(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FORTRAN_MCP_SEARCH_PROVIDER", "wrong")

    report = diagnose()

    assert report.search_provider == "invalid"


def test_doctor_lists_installed_bundles(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    installed = _installed_core(tmp_path)
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(installed))

    main([])

    output = capsys.readouterr().out
    assert "Data:" in output
    assert "core " in output
    assert "(1 sources)" in output
    assert "Ready:" not in output
    assert "Next:" not in output


def test_doctor_lists_custom_data_without_prescribing_actions(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    prepare_index(data_dir)
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(data_dir))

    main([])

    output = capsys.readouterr().out
    assert "custom lexical index (" in output
    assert "chunks)" in output
    assert "Ready:" not in output
    assert "Next:" not in output


def test_doctor_json_is_machine_readable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))

    main(["--json"])

    output = capsys.readouterr().out
    assert '"data_directory"' in output
    assert '"search_provider"' in output
    assert '"ready"' not in output
    assert '"actions"' not in output
