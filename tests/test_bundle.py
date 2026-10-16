"""Tests for reproducible documentation bundles."""

import sqlite3
import zipfile
from pathlib import Path

import pytest

from fortran_mcp.bundle import (
    BUNDLE_ROOT,
    BundleError,
    build_bundle,
    install_bundle,
    verify_bundle,
)


def _bundle_inputs(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "fortran-mcp.db") as database:
        database.execute("CREATE TABLE chunks(source_id TEXT)")
        database.executemany(
            "INSERT INTO chunks VALUES (?)",
            (("fpm-0.13.0-docs",), ("stdlib-0.8.1-docs",)),
        )
    license_dir = tmp_path / "licenses"
    license_dir.mkdir()
    for source_id in ("fpm-0.13.0-docs", "stdlib-0.8.1-docs"):
        (license_dir / f"{source_id}.txt").write_text(f"License for {source_id}\n")
    return data_dir, license_dir


def test_core_bundle_is_reproducible_and_verifiable(tmp_path: Path) -> None:
    data_dir, license_dir = _bundle_inputs(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    manifest = build_bundle(
        "core", first, data_dir=data_dir, license_dir=license_dir, data_version="2026.08.1"
    )
    build_bundle(
        "core", second, data_dir=data_dir, license_dir=license_dir, data_version="2026.08.1"
    )

    assert first.read_bytes() == second.read_bytes()
    assert verify_bundle(first) == manifest
    assert manifest.role == "core"
    assert [source.id for source in manifest.sources] == [
        "fpm-0.13.0-docs",
        "stdlib-0.8.1-docs",
    ]
    assert {record.path for record in manifest.files} == {
        "indexes/fortran-mcp.db",
        "licenses/fpm-0.13.0-docs.txt",
        "licenses/stdlib-0.8.1-docs.txt",
    }


def test_semantic_bundle_declares_exact_core_requirement(tmp_path: Path) -> None:
    data_dir, _ = _bundle_inputs(tmp_path)
    with sqlite3.connect(data_dir / "fortran-mcp-semantic.db") as database:
        database.execute("CREATE TABLE vectors(source_id TEXT)")
        database.executemany(
            "INSERT INTO vectors VALUES (?)",
            (("fpm-0.13.0-docs",), ("stdlib-0.8.1-docs",)),
        )
        database.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        database.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (
                ("model", "test/model"),
                ("dimensions", "384"),
                ("lexical_index_sha256", "a" * 64),
            ),
        )

    manifest = build_bundle(
        "semantic", tmp_path / "semantic.zip", data_dir=data_dir, data_version="2026.08.1"
    )

    assert manifest.embedding_model == "test/model"
    assert manifest.embedding_dimensions == 384
    assert manifest.requires[0].lexical_index_sha256 == "a" * 64


def test_bundle_verification_rejects_undeclared_file(tmp_path: Path) -> None:
    data_dir, license_dir = _bundle_inputs(tmp_path)
    artifact = tmp_path / "bundle.zip"
    build_bundle(
        "core", artifact, data_dir=data_dir, license_dir=license_dir, data_version="2026.08.1"
    )
    with zipfile.ZipFile(artifact, "a") as archive:
        archive.writestr(f"{BUNDLE_ROOT}/unexpected.txt", "unexpected")

    with pytest.raises(BundleError, match="do not match"):
        verify_bundle(artifact)


def test_core_bundle_requires_source_license_text(tmp_path: Path) -> None:
    data_dir, license_dir = _bundle_inputs(tmp_path)
    (license_dir / "fpm-0.13.0-docs.txt").unlink()

    with pytest.raises(BundleError, match="required bundle file"):
        build_bundle(
            "core",
            tmp_path / "bundle.zip",
            data_dir=data_dir,
            license_dir=license_dir,
            data_version="2026.08.1",
        )


def test_install_core_then_compatible_semantic_bundle(tmp_path: Path) -> None:
    data_dir, license_dir = _bundle_inputs(tmp_path)
    core = tmp_path / "core.zip"
    build_bundle("core", core, data_dir=data_dir, license_dir=license_dir, data_version="2026.08.1")
    core_hash = verify_bundle(core).files[0].sha256
    with sqlite3.connect(data_dir / "fortran-mcp-semantic.db") as database:
        database.execute("CREATE TABLE vectors(source_id TEXT)")
        database.execute("INSERT INTO vectors VALUES ('fpm-0.13.0-docs')")
        database.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        database.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (
                ("model", "test/model"),
                ("dimensions", "384"),
                ("lexical_index_sha256", core_hash),
            ),
        )
    semantic = tmp_path / "semantic.zip"
    build_bundle("semantic", semantic, data_dir=data_dir, data_version="2026.08.1")
    installed = tmp_path / "installed"

    install_bundle(core, data_dir=installed)
    install_bundle(semantic, data_dir=installed)

    assert (installed / "fortran-mcp.db").is_file()
    assert (installed / "fortran-mcp-semantic.db").is_file()
    assert (installed / "manifests/core.json").is_file()
    assert (installed / "manifests/semantic.json").is_file()


def test_semantic_install_requires_core_bundle(tmp_path: Path) -> None:
    data_dir, _ = _bundle_inputs(tmp_path)
    with sqlite3.connect(data_dir / "fortran-mcp-semantic.db") as database:
        database.execute("CREATE TABLE vectors(source_id TEXT)")
        database.execute("INSERT INTO vectors VALUES ('fpm-0.13.0-docs')")
        database.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        database.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (
                ("model", "test/model"),
                ("dimensions", "384"),
                ("lexical_index_sha256", "a" * 64),
            ),
        )
    semantic = tmp_path / "semantic.zip"
    build_bundle("semantic", semantic, data_dir=data_dir, data_version="2026.08.1")

    with pytest.raises(BundleError, match="core bundle"):
        install_bundle(semantic, data_dir=tmp_path / "installed")
