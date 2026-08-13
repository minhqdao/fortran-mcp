"""Tests for local bundle discovery catalogs."""

import sqlite3
from pathlib import Path

import pytest

from fortran_mcp.bundle import build_bundle
from fortran_mcp.catalog import (
    CatalogError,
    build_catalog,
    install_from_catalog,
    load_catalog,
)


def _core_bundle(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "fortran-mcp.db") as database:
        database.execute("CREATE TABLE chunks(source_id TEXT)")
        database.execute("INSERT INTO chunks VALUES ('fpm-0.13.0-docs')")
    license_dir = tmp_path / "licenses"
    license_dir.mkdir()
    (license_dir / "fpm-0.13.0-docs.txt").write_text("MIT\n")
    bundle = tmp_path / "release" / "fortran-mcp-core.zip"
    build_bundle("core", bundle, data_dir=data_dir, license_dir=license_dir)
    return bundle


def test_catalog_is_deterministic_and_uses_relative_artifact_paths(tmp_path: Path) -> None:
    bundle = _core_bundle(tmp_path)
    first = bundle.parent / "catalog.json"
    second = bundle.parent / "catalog-copy.json"

    catalog = build_catalog("2026.08.1", first, [bundle])
    build_catalog("2026.08.1", second, [bundle])

    assert first.read_bytes() == second.read_bytes()
    assert load_catalog(first) == catalog
    assert catalog.bundles[0].path == "fortran-mcp-core.zip"
    assert catalog.bundles[0].size == bundle.stat().st_size


def test_catalog_installs_verified_local_bundle(tmp_path: Path) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])
    destination = tmp_path / "installed"

    manifest = install_from_catalog("core", catalog_path, data_dir=destination)

    assert manifest.role == "core"
    assert (destination / "fortran-mcp.db").is_file()


def test_catalog_rejects_changed_artifact(tmp_path: Path) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])
    bundle.write_bytes(bundle.read_bytes() + b"changed")

    with pytest.raises(CatalogError, match="failed verification"):
        install_from_catalog("core", catalog_path, data_dir=tmp_path / "installed")


def test_catalog_rejects_artifacts_outside_its_directory(tmp_path: Path) -> None:
    bundle = _core_bundle(tmp_path)

    with pytest.raises(CatalogError, match="inside the catalog directory"):
        build_catalog("2026.08.1", tmp_path / "other" / "catalog.json", [bundle])


def test_catalog_rejects_unknown_role(tmp_path: Path) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])

    with pytest.raises(CatalogError, match="semantic"):
        install_from_catalog("semantic", catalog_path)
