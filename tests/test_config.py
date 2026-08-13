"""Tests for runtime storage configuration."""

from pathlib import Path

from pytest import MonkeyPatch

from fortran_mcp.config import DATA_DIR_ENV, data_directory
from fortran_mcp.search import SQLiteSearchProvider


def test_data_directory_defaults_to_project_data(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)

    assert data_directory() == Path("data")


def test_data_directory_and_provider_follow_environment(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))

    assert data_directory() == tmp_path
    assert SQLiteSearchProvider().index_path == tmp_path / "fortran-mcp.db"
