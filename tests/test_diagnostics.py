"""Tests for first-run diagnostics."""

from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from fortran_mcp.diagnostics import diagnose, main


def test_doctor_explains_how_to_install_missing_core(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FORTRAN_MCP_SEARCH_PROVIDER", raising=False)

    report = diagnose()

    assert report.ready is False
    assert report.search_provider == "lexical"
    assert report.actions == ("Install core data: fortran-mcp data install core",)


def test_doctor_reports_invalid_provider_as_an_action(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FORTRAN_MCP_SEARCH_PROVIDER", "wrong")

    report = diagnose()

    assert report.search_provider == "invalid"
    assert "Set FORTRAN_MCP_SEARCH_PROVIDER" in report.actions[0]


def test_doctor_json_is_machine_readable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FORTRAN_MCP_DATA_DIR", str(tmp_path))

    main(["--json"])

    output = capsys.readouterr().out
    assert '"ready": false' in output
    assert '"data_directory"' in output
