"""Tests for documentation source metadata validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from fortran_mcp.sources import CitationLocation, SourceRegistry, load_registry

REGISTRY_PATH = Path(__file__).parents[1] / "docs" / "sources.toml"


def test_project_registry_is_valid() -> None:
    registry = load_registry(REGISTRY_PATH)

    assert registry.schema_version == 1
    assert len(registry.sources) == 23
    # Spot-check key properties of specific sources by ID, not by position.
    registry.get("fpm-0.13.0-docs")
    gfortran = registry.get("gfortran-16.2.0-manual")
    assert gfortran.expected_document_count == 485
    assert gfortran.excluded_document_paths == ("manual/Keyword-Index.md",)
    cmake = registry.get("cmake-4.4.0-fortran-docs")
    assert cmake.expected_document_count == 35
    registry.get("fortran-lang-intrinsics-reference")
    registry.get("gnu-make-4.4.1-build-reference")
    fypp = registry.get("fypp-3.2-manual")
    assert fypp.expected_document_count == 1
    fortitude = registry.get("fortitude-0.9.2-reference")
    assert fortitude.expected_document_count == 111
    codee = registry.get("codee-open-catalog-fortran-subset")
    assert codee.expected_document_count == 5
    idioms = registry.get("old-fortran-programming-idioms")
    assert idioms.expected_document_count == 9
    prima = registry.get("prima-modernization-case-study")
    assert prima.expected_document_count == 1
    registry.get("beliavsky-fortran-packages-list")
    registry.get("fortran-lang-package-index-additions")


def test_registry_get_missing_id_raises_keyerror() -> None:
    registry = load_registry(REGISTRY_PATH)

    with pytest.raises(KeyError, match="nonexistent-source"):
        registry.get("nonexistent-source")


def test_packaged_registry_is_available() -> None:
    assert load_registry().sources


def test_registry_rejects_duplicate_source_ids() -> None:
    source = load_registry(REGISTRY_PATH).sources[0].model_dump(mode="json")

    with pytest.raises(ValidationError, match="source IDs must be unique"):
        SourceRegistry.model_validate({"schema_version": 1, "sources": [source, source]})


def test_citation_requires_a_location() -> None:
    with pytest.raises(ValidationError, match="citation requires"):
        CitationLocation()
