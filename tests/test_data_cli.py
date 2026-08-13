"""Tests for user-facing data management."""

import json
import sqlite3
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from fortran_mcp.bundle import BundleError, build_bundle, install_bundle
from fortran_mcp.data_cli import data_status, inspect_role, main, remove_data


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

    main(["remove", "--data-dir", str(installed), "--yes"])

    assert unrelated.read_text() == "keep me"
    assert data_status(installed).bundles[0].installed is False
    assert not (installed / "fortran-mcp.db").exists()
    assert "Removed 3 managed files" in capsys.readouterr().out


def test_remove_requires_confirmation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    installed = _installed_core(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    main(["remove", "--data-dir", str(installed)])

    assert (installed / "fortran-mcp.db").is_file()


def test_remove_rejects_unsafe_manifest_path(tmp_path: Path) -> None:
    installed = _installed_core(tmp_path)
    manifest_path = installed / "manifests/core.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../../outside.txt"
    manifest_path.write_text(json.dumps(manifest))

    try:
        remove_data(installed)
    except BundleError as error:
        assert "unsafe path" in str(error)
    else:
        raise AssertionError("unsafe manifest path was accepted")
