"""Build, validate, and consume local data-bundle catalogs."""

import argparse
import hashlib
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, Self, cast
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from pydantic import Field, model_validator

from fortran_mcp.bundle import (
    DOWNLOAD_LIMIT,
    BundleError,
    BundleManifest,
    install_bundle,
    verify_bundle,
)
from fortran_mcp.config import data_directory
from fortran_mcp.sources import StrictModel

CATALOG_SCHEMA_VERSION: Literal[1] = 1
CATALOG_DOWNLOAD_LIMIT = 1024 * 1024
DEFAULT_CATALOG_URL = (
    "https://github.com/minhqdao/fortran-mcp/releases/latest/download/catalog.json"
)
BundleRole = Literal["core", "semantic"]
CatalogLocation = str | Path


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
        decoded_path = PurePosixPath(unquote(self.path))
        parsed = urlparse(self.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or decoded_path.is_absolute()
            or ".." in decoded_path.parts
            or not path.parts
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\\" in unquote(self.path)
        ):
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


def _validate_catalog(content: bytes, location: CatalogLocation) -> BundleCatalog:
    try:
        return BundleCatalog.model_validate_json(content)
    except ValueError as error:
        raise CatalogError(f"invalid catalog from {location}: {error}") from error


def _download_catalog(url: str) -> bytes:
    if urlparse(url).scheme != "https":
        raise CatalogError("remote catalog URL must use HTTPS")
    request = Request(url, headers={"User-Agent": "fortran-mcp/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > CATALOG_DOWNLOAD_LIMIT:
                raise CatalogError("catalog download exceeds the size limit")
            content = cast("bytes", response.read(CATALOG_DOWNLOAD_LIMIT + 1))
            if len(content) > CATALOG_DOWNLOAD_LIMIT:
                raise CatalogError("catalog download exceeds the size limit")
            resolved_url = response.geturl()
            if urlparse(resolved_url).scheme != "https":
                raise CatalogError("remote catalog redirected to a non-HTTPS URL")
            return content
    except (OSError, ValueError) as error:
        raise CatalogError(
            f"could not download catalog from {url}: {error}. "
            "Check network access or pass --catalog PATH_OR_HTTPS_URL"
        ) from error


def _load_catalog_source(location: CatalogLocation) -> tuple[BundleCatalog, Path | str]:
    text = str(location)
    parsed = urlparse(text)
    windows_path = len(text) >= 3 and text[1] == ":" and text[2] in {"/", "\\"}
    if not isinstance(location, Path) and parsed.scheme and not windows_path:
        content = _download_catalog(text)
        return _validate_catalog(content, text), text
    path = Path(location).expanduser()
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CatalogError(
            f"could not read catalog at {path}: {error}. "
            "Pass an existing local path or an HTTPS URL"
        ) from error
    return _validate_catalog(content, path), path


def load_catalog(location: CatalogLocation) -> BundleCatalog:
    """Load and strictly validate a local or HTTPS catalog."""
    return _load_catalog_source(location)[0]


def _catalog_artifact(catalog_path: Path, entry: CatalogBundle) -> Path:
    artifact = catalog_path.parent.joinpath(*PurePosixPath(entry.path).parts)
    try:
        size = artifact.stat().st_size
    except OSError as error:
        raise CatalogError(f"catalog bundle is unavailable: {entry.path}") from error
    if size != entry.size or _sha256(artifact) != entry.sha256:
        raise CatalogError(f"catalog bundle failed verification: {entry.path}")
    return artifact


def _download_catalog_artifact(url: str, entry: CatalogBundle, destination: Path) -> None:
    if urlparse(url).scheme != "https":
        raise CatalogError("remote bundle URL must use HTTPS")
    if entry.size > DOWNLOAD_LIMIT:
        raise CatalogError(f"catalog bundle exceeds the size limit: {entry.path}")
    request = Request(url, headers={"User-Agent": "fortran-mcp/0.1"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            if urlparse(response.geturl()).scheme != "https":
                raise CatalogError("remote bundle redirected to a non-HTTPS URL")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != entry.size:
                raise CatalogError(f"catalog bundle has an unexpected size: {entry.path}")
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > entry.size or total > DOWNLOAD_LIMIT:
                    raise CatalogError(f"catalog bundle has an unexpected size: {entry.path}")
                output.write(block)
    except (OSError, ValueError) as error:
        raise CatalogError(f"could not download {entry.role} bundle from {url}: {error}") from error
    if destination.stat().st_size != entry.size or _sha256(destination) != entry.sha256:
        raise CatalogError(f"downloaded {entry.role} bundle failed catalog verification")


def install_from_catalog(
    role: BundleRole,
    catalog_location: CatalogLocation,
    *,
    data_dir: Path | None = None,
) -> BundleManifest:
    """Verify and install one role from a local or HTTPS catalog."""
    catalog, base = _load_catalog_source(catalog_location)
    entry = next((bundle for bundle in catalog.bundles if bundle.role == role), None)
    if entry is None:
        raise CatalogError(f"catalog does not contain the {role} bundle")
    if isinstance(base, Path):
        artifact = _catalog_artifact(base, entry)
        manifest = verify_bundle(artifact)
        if manifest.bundle_id != entry.bundle_id or manifest.bundle_version != entry.bundle_version:
            raise CatalogError("catalog metadata does not match the bundle manifest")
        return install_bundle(artifact, data_dir=data_dir)

    with tempfile.TemporaryDirectory(prefix=".fortran-mcp-catalog-") as temporary:
        artifact = Path(temporary) / "bundle.zip"
        _download_catalog_artifact(urljoin(base, entry.path), entry, artifact)
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
    install.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_URL,
        help="local catalog path or HTTPS URL",
    )
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
    except (BundleError, CatalogError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
