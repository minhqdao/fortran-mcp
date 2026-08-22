"""Tests for user-facing data management."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest import CaptureFixture, MonkeyPatch

from fortran_mcp.bundle import BundleError, build_bundle, install_bundle
from fortran_mcp.catalog import DEFAULT_CATALOG_URL, build_catalog
from fortran_mcp.data_cli import data_status, inspect_role, main, remove_data
from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import SQLiteSearchProvider, build_index

from .test_provision import _release


def _installed_core(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "fortran-mcp.db") as database:
        database.execute("CREATE TABLE chunks(source_id TEXT)")
        database.execute("INSERT INTO chunks VALUES ('fpm-0.13.0-docs')")
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    (licenses / "fpm-0.13.0-docs.txt").write_text("MIT\n")
    bundle = tmp_path / "core.zip"
    build_bundle("core", bundle, data_dir=source, license_dir=licenses)
    installed = tmp_path / "installed"
    install_bundle(bundle, data_dir=installed)
    return installed


def test_data_status_reports_valid_core_and_provider_readiness(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)

    status = data_status(installed)

    assert status.bundles[0].valid is True
    assert status.bundles[0].sources == ("fpm-0.13.0-docs",)
    assert status.bundles[1].installed is False
    assert status.lexical_ready is True
    assert status.semantic_ready is False
    assert status.hybrid_ready is False


def test_installed_bundle_verification_detects_modified_file(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)
    (installed / "fortran-mcp.db").write_bytes(b"changed")

    result = inspect_role("core", installed)

    assert result.installed is True
    assert result.valid is False
    assert "failed verification" in str(result.error)


def test_installed_bundle_verification_detects_invalid_manifest(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)
    manifest_path = installed / "manifests/core.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["role"] = "semantic"
    manifest_path.write_text(json.dumps(manifest))

    result = inspect_role("core", installed)

    assert result.valid is False
    assert "does not match" in str(result.error)


def test_remove_deletes_managed_bundle_data_and_preserves_other_files(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    installed = _installed_core(tmp_path)
    unrelated = installed / "notes.txt"
    unrelated.write_text("keep me")

    main(["remove", "core", "--data-dir", str(installed), "--yes"])

    assert unrelated.read_text() == "keep me"
    assert data_status(installed).bundles[0].installed is False
    assert not (installed / "fortran-mcp.db").exists()
    assert "Removed the core data package (3 files)" in capsys.readouterr().out


def test_remove_requires_confirmation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    installed = _installed_core(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    main(["remove", "core", "--data-dir", str(installed)])

    assert (installed / "fortran-mcp.db").is_file()


def test_remove_with_confirmation_yes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    installed = _installed_core(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    main(["remove", "core", "--data-dir", str(installed)])

    assert not (installed / "fortran-mcp.db").exists()


def test_remove_requires_a_package_argument(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)

    with pytest.raises(SystemExit):
        main(["remove", "--data-dir", str(installed)])
    assert (installed / "fortran-mcp.db").is_file()


def test_remove_rejects_uninstalled_package(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    installed = tmp_path / "empty"
    installed.mkdir()

    with pytest.raises(SystemExit):
        main(["remove", "core", "--data-dir", str(installed), "--yes"])
    assert "is not installed" in capsys.readouterr().err


def test_remove_core_is_blocked_while_semantic_is_installed(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    installed = _installed_core(tmp_path)
    manifests = installed / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "semantic.json").write_text("{}\n")

    with pytest.raises(SystemExit):
        main(["remove", "core", "--data-dir", str(installed), "--yes"])
    assert "remove the semantic data package first" in capsys.readouterr().err


def test_remove_semantic_keeps_files_core_still_needs(tmp_path: Path) -> None:
    catalog = _release(tmp_path)
    installed = tmp_path / "installed"
    for package in ("core", "semantic"):
        main(["install", package, "--catalog", str(catalog), "--data-dir", str(installed)])

    main(["remove", "semantic", "--data-dir", str(installed), "--yes"])

    status = data_status(installed)
    assert status.bundles[0].valid is True
    assert status.bundles[1].installed is False
    assert (installed / "fortran-mcp.db").is_file()
    assert (installed / "manifests" / "core.json").is_file()
    assert not (installed / "fortran-mcp-semantic.db").exists()
    assert not (installed / "manifests" / "semantic.json").exists()
    assert (installed / "licenses" / "fpm-0.13.0-docs.txt").is_file()


def test_data_verify_cli_reports_ok_for_valid_install(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    installed = _installed_core(tmp_path)

    main(["verify", "--data-dir", str(installed)])

    assert "Installed data packages verified" in capsys.readouterr().out


def test_data_verify_cli_rejects_corrupted_install(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    installed = _installed_core(tmp_path)
    (installed / "fortran-mcp.db").write_bytes(b"corrupted")

    with pytest.raises(SystemExit):
        main(["verify", "--data-dir", str(installed)])
    assert "verification failed" in capsys.readouterr().err


def test_data_verify_reports_when_nothing_is_installed(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    installed = tmp_path / "empty"
    installed.mkdir()

    main(["verify", "--data-dir", str(installed)])

    assert "No data packages are installed" in capsys.readouterr().out


def test_remove_rejects_unsafe_manifest_path(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)
    manifest_path = installed / "manifests/core.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../../outside.txt"
    manifest_path.write_text(json.dumps(manifest))

    try:
        remove_data("core", installed)
    except BundleError as error:
        assert "manifest is invalid" in str(error)
    else:
        raise AssertionError("unsafe manifest path was accepted")


def test_install_uses_default_release_catalog(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    called: list[tuple[str, str, Path]] = []

    def install(role: str, catalog: str, *, data_dir: Path) -> SimpleNamespace:
        called.append((role, catalog, data_dir))
        return SimpleNamespace(bundle_id="fortran-mcp-core-test")

    monkeypatch.setattr("fortran_mcp.data_cli.install_from_catalog", install)

    main(["install", "core", "--data-dir", str(tmp_path)])

    assert called == [("core", DEFAULT_CATALOG_URL, tmp_path)]
    assert "Installed fortran-mcp-core-test" in capsys.readouterr().out


def test_local_catalog_install_reaches_first_search(tmp_path: Path) -> None:
    release_data = tmp_path / "release-data"
    chunks = release_data / "chunks"
    chunks.mkdir(parents=True)
    chunk = DocumentChunk(
        id="a" * 32,
        source_id="fpm-0.13.0-docs",
        revision="5097350c24ea7b5ceec233714f5a2604f79d0c02",
        path="pages/spec/manifest.md",
        headings=("Manifest reference", "OpenMP"),
        line_start=1,
        line_end=2,
        text="Add OpenMP as a built-in metapackage dependency in fpm.toml.",
        sha256="b" * 64,
    )
    (chunks / "fpm.jsonl").write_text(chunk.model_dump_json() + "\n")
    build_index(release_data)
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    (licenses / "fpm-0.13.0-docs.txt").write_text("MIT\n")
    release = tmp_path / "release"
    bundle = release / "fortran-mcp-core.zip"
    build_bundle("core", bundle, data_dir=release_data, license_dir=licenses)
    catalog = release / "catalog.json"
    build_catalog("2026.08.1", catalog, [bundle])
    installed = tmp_path / "installed"

    main(
        [
            "install",
            "core",
            "--catalog",
            str(catalog),
            "--data-dir",
            str(installed),
        ]
    )
    results = SQLiteSearchProvider(installed / "fortran-mcp.db").search("OpenMP dependency")

    assert data_status(installed).lexical_ready is True
    assert results[0].chunk_id == chunk.id
    assert str(results[0].url) == "https://fpm.fortran-lang.org/spec/manifest.html"
