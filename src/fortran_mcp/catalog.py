"""Build, validate, and consume local data-bundle catalogs."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import Field, model_validator

from fortran_mcp.bundle import BundleManifest, install_bundle, verify_bundle
from fortran_mcp.config import data_directory
from fortran_mcp.sources import StrictModel

CATALOG_SCHEMA_VERSION: Literal[1] = 1
BundleRole = Literal["core", "semantic"]


class CatalogError(RuntimeError):
    """Raised when a bundle catalog cannot be built or consumed."""


class CatalogBundle(StrictModel):
    """One complete bundle artifact advertised by a catalog."""

    role: BundleRole
    path: str = Field(min_length=1)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def path_is_safe_and_relative(self) -> Self:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("catalog bundle path must be safe and relative")
        return self


class BundleCatalog(StrictModel):
    """Versioned discovery document for one compatible bundle set."""

    schema_version: Literal[1]
    data_version: str = Field(pattern=r"^[0-9]{4}\.[0-9]{2}\.[0-9]+$")
    bundles: tuple[CatalogBundle, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def roles_are_unique(self) -> Self:
        roles = [bundle.role for bundle in self.bundles]
        if len(roles) != len(set(roles)):
            raise ValueError("catalog bundle roles must be unique")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CatalogError(f"could not read bundle artifact: {path}") from error
    return digest.hexdigest()


def _relative_artifact_path(artifact: Path, catalog_path: Path) -> str:
    try:
        return artifact.resolve().relative_to(catalog_path.parent.resolve()).as_posix()
    except ValueError as error:
        raise CatalogError("bundle artifacts must be inside the catalog directory") from error


def build_catalog(
    data_version: str,
    output: Path,
    artifacts: Sequence[Path],
) -> BundleCatalog:
    """Build a deterministic local catalog from verified bundle artifacts."""
    entries: list[CatalogBundle] = []
    for artifact in artifacts:
        manifest = verify_bundle(artifact)
        entries.append(
            CatalogBundle(
                role=manifest.role,
                path=_relative_artifact_path(artifact, output),
                size=artifact.stat().st_size,
                sha256=_sha256(artifact),
                bundle_id=manifest.bundle_id,
                bundle_version=manifest.bundle_version,
            )
        )
    try:
        catalog = BundleCatalog(
            schema_version=CATALOG_SCHEMA_VERSION,
            data_version=data_version,
            bundles=tuple(sorted(entries, key=lambda entry: entry.role)),
        )
    except ValueError as error:
        raise CatalogError(f"could not build catalog: {error}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog.model_dump(mode="json"), indent=2) + "\n")
    return catalog


def load_catalog(path: Path) -> BundleCatalog:
    """Load and strictly validate a local catalog."""
    try:
        return BundleCatalog.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CatalogError(f"invalid catalog: {error}") from error


def _catalog_artifact(catalog_path: Path, entry: CatalogBundle) -> Path:
    artifact = catalog_path.parent.joinpath(*PurePosixPath(entry.path).parts)
    try:
        size = artifact.stat().st_size
    except OSError as error:
        raise CatalogError(f"catalog bundle is unavailable: {entry.path}") from error
    if size != entry.size or _sha256(artifact) != entry.sha256:
        raise CatalogError(f"catalog bundle failed verification: {entry.path}")
    return artifact


def install_from_catalog(
    role: BundleRole,
    catalog_path: Path,
    *,
    data_dir: Path | None = None,
) -> BundleManifest:
    """Verify and install one role from an explicitly supplied local catalog."""
    catalog = load_catalog(catalog_path)
    entry = next((bundle for bundle in catalog.bundles if bundle.role == role), None)
    if entry is None:
        raise CatalogError(f"catalog does not contain the {role} bundle")
    artifact = _catalog_artifact(catalog_path, entry)
    manifest = verify_bundle(artifact)
    if manifest.bundle_id != entry.bundle_id or manifest.bundle_version != entry.bundle_version:
        raise CatalogError("catalog metadata does not match the bundle manifest")
    return install_bundle(artifact, data_dir=data_dir)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or consume local bundle catalogs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--data-version", required=True)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("artifacts", nargs="+", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("path", type=Path)
    install = subparsers.add_parser("install")
    install.add_argument("role", choices=("core", "semantic"))
    install.add_argument("--catalog", required=True, type=Path)
    install.add_argument("--data-dir", type=Path, default=data_directory())
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Build, validate, or install from a local catalog."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            catalog = build_catalog(args.data_version, args.output, args.artifacts)
            print(f"Built data catalog {catalog.data_version}: {args.output}")
        elif args.command == "verify":
            catalog = load_catalog(args.path)
            for entry in catalog.bundles:
                _catalog_artifact(args.path, entry)
            print(f"Verified data catalog {catalog.data_version}: {args.path}")
        else:
            manifest = install_from_catalog(
                args.role,
                args.catalog,
                data_dir=args.data_dir,
            )
            print(f"Installed {manifest.bundle_id} into {args.data_dir}")
    except CatalogError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
