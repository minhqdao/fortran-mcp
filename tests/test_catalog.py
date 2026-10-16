"""Tests for local bundle discovery catalogs."""

import sqlite3
from io import BytesIO
from pathlib import Path
from urllib.request import Request

import pytest

from fortran_mcp.bundle import build_bundle
from fortran_mcp.catalog import (
    DEFAULT_CATALOG_URL,
    CatalogBundle,
    CatalogError,
    build_catalog,
    install_from_catalog,
    load_catalog,
)
from fortran_mcp.catalog import (
    main as catalog_main,
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
    build_bundle(
        "core", bundle, data_dir=data_dir, license_dir=license_dir, data_version="2026.08.1"
    )
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


@pytest.mark.parametrize("path", ["../core.zip", "%2e%2e/core.zip", "https://evil/core.zip"])
def test_catalog_rejects_unsafe_remote_artifact_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe and relative"):
        CatalogBundle(
            role="core",
            path=path,
            size=1,
            sha256="a" * 64,
            bundle_id="core",
        )


def test_remote_catalog_resolves_and_verifies_relative_bundle_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])
    resolved_catalog = (
        "https://github.com/minhqdao/fortran-mcp/releases/download/v0.1.0/catalog.json"
    )
    responses = [
        (catalog_path.read_bytes(), resolved_catalog),
        (bundle.read_bytes(), resolved_catalog.removesuffix("catalog.json") + bundle.name),
    ]
    requested: list[str] = []

    class Response:
        def __init__(self, content: bytes, url: str) -> None:
            self.stream = BytesIO(content)
            self.headers = {"Content-Length": str(len(content))}
            self.url = url

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self.stream.read(size)

        def geturl(self) -> str:
            return self.url

    def fake_urlopen(request: Request, *, timeout: int) -> Response:
        requested.append(request.full_url)
        content, url = responses.pop(0)
        return Response(content, url)

    monkeypatch.setattr("fortran_mcp.catalog.urlopen", fake_urlopen)
    destination = tmp_path / "installed"

    manifest = install_from_catalog("core", DEFAULT_CATALOG_URL, data_dir=destination)

    assert manifest.role == "core"
    assert requested == [
        DEFAULT_CATALOG_URL,
        "https://github.com/minhqdao/fortran-mcp/releases/latest/download/fortran-mcp-core.zip",
    ]
    assert (destination / "fortran-mcp.db").is_file()


def test_remote_catalog_failure_suggests_local_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(*_args: object, **_kwargs: object) -> None:
        raise OSError("offline")

    monkeypatch.setattr("fortran_mcp.catalog.urlopen", offline)

    with pytest.raises(CatalogError, match=r"Check network access or pass --catalog"):
        load_catalog(DEFAULT_CATALOG_URL)


def test_catalog_verify_cli_passes_for_valid_catalog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])

    catalog_main(["verify", str(catalog_path)])

    assert "Verified" in capsys.readouterr().out


def test_catalog_verify_cli_rejects_corrupted_artifact(
    tmp_path: Path,
) -> None:
    bundle = _core_bundle(tmp_path)
    catalog_path = bundle.parent / "catalog.json"
    build_catalog("2026.08.1", catalog_path, [bundle])
    bundle.write_bytes(bundle.read_bytes() + b"x")

    with pytest.raises(SystemExit):
        catalog_main(["verify", str(catalog_path)])
