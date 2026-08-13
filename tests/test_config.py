"""Tests for runtime storage configuration."""

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from fortran_mcp.config import (
    DATA_DIR_ENV,
    SEARCH_PROVIDER_ENV,
    data_directory,
    search_provider_name,
    user_data_directory,
)
from fortran_mcp.search import SQLiteSearchProvider


def test_data_directory_defaults_to_user_data(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)

    assert data_directory() == user_data_directory()


def test_data_directory_and_provider_follow_environment(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))

    assert data_directory() == tmp_path
    assert SQLiteSearchProvider().index_path == tmp_path / "fortran-mcp.db"


def test_search_provider_defaults_to_lexical(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv(SEARCH_PROVIDER_ENV, raising=False)

    assert search_provider_name() == "lexical"


def test_search_provider_validates_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(SEARCH_PROVIDER_ENV, "HYBRID")
    assert search_provider_name() == "hybrid"

    monkeypatch.setenv(SEARCH_PROVIDER_ENV, "unknown")
    with pytest.raises(ValueError, match=SEARCH_PROVIDER_ENV):
        search_provider_name()
