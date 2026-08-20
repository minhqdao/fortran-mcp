"""Tests for documentation source metadata validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from fortran_mcp.sources import CitationLocation, SourceRegistry, load_registry

REGISTRY_PATH = Path(__file__).parents[1] / "docs" / "sources.toml"


def test_project_registry_is_valid() -> None:
    registry = load_registry(REGISTRY_PATH)

    assert registry.schema_version == 1
    assert registry.sources[0].id == "fpm-0.13.0-docs"
    assert registry.sources[1].id == "stdlib-0.8.1-docs"
    assert registry.sources[2].id == "gfortran-16.2.0-manual"
    assert registry.sources[2].expected_document_count == 485
    assert registry.sources[3].id == "cmake-4.4.0-fortran-docs"
    assert registry.sources[3].expected_document_count == 35
    assert len(registry.sources) == 17
    assert registry.sources[4].id == "fortran-lang-intrinsics-reference"
    assert registry.sources[-4].id == "gnu-make-4.4.1-build-reference"
    assert registry.sources[-3].id == "numpy-2.5.2-f2py-docs"
    assert registry.sources[-2].id == "openmpi-5.0.10-fortran-reference"
    assert registry.sources[-1].id == "fortitude-0.9.2-reference"
    assert registry.sources[-1].expected_document_count == 111


def test_packaged_registry_is_available() -> None:
    assert load_registry().sources


def test_registry_rejects_duplicate_source_ids() -> None:
    source = load_registry(REGISTRY_PATH).sources[0].model_dump(mode="json")

    with pytest.raises(ValidationError, match="source IDs must be unique"):
        SourceRegistry.model_validate({"schema_version": 1, "sources": [source, source]})


def test_citation_requires_a_location() -> None:
    with pytest.raises(ValidationError, match="citation requires"):
        CitationLocation()
