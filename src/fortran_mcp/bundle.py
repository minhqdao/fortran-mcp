"""Build and verify reproducible documentation data bundles."""

import argparse
import hashlib
import json
import sqlite3
import zipfile
from collections.abc import Sequence
from importlib.metadata import version as package_version
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME
from fortran_mcp.sources import Source, StrictModel, load_registry

BUNDLE_SCHEMA_VERSION: Literal[1] = 1
BUNDLE_ROOT = "fortran-mcp-bundle"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class BundleError(RuntimeError):
    """Raised when a bundle cannot be built or verified."""


class BundleFile(StrictModel):
    """Integrity record for one bundled payload file."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BundleSource(StrictModel):
    """Source provenance and licensing embedded in a bundle manifest."""

    id: str
    version: str
    revision: str
    document_type: str
    authority: str
    topics: tuple[str, ...]
    license: str
    license_url: str


class BundleRequirement(StrictModel):
    """A required companion artifact and its exact payload checksum."""

    role: Literal["core"]
    lexical_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BundleManifest(StrictModel):
    """Stable, machine-readable contract for one data bundle."""

    schema_version: Literal[1]
    bundle_id: str
    role: Literal["core", "semantic"]
    bundle_version: str
    server_compatibility: str
    sources: tuple[BundleSource, ...]
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1)
    requires: tuple[BundleRequirement, ...] = ()
    files: tuple[BundleFile, ...]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source_ids(index: Path, table: str) -> tuple[str, ...]:
    try:
        with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as database:
            return tuple(
                row[0]
                for row in database.execute(
                    f"SELECT DISTINCT source_id FROM {table} ORDER BY source_id"
                ).fetchall()
            )
    except sqlite3.Error as error:
        raise BundleError(f"could not inspect {index}: {error}") from error


def _semantic_metadata(index: Path) -> dict[str, str]:
    try:
        with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as database:
            return dict(database.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error as error:
        raise BundleError(f"could not inspect {index}: {error}") from error


def _manifest_source(source: Source) -> BundleSource:
    return BundleSource(
        id=source.id,
        version=source.version,
        revision=source.revision,
        document_type=source.document_type,
        authority=source.authority,
        topics=source.topics,
        license=source.license,
        license_url=str(source.license_url),
    )


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{BUNDLE_ROOT}/{path}", ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def build_bundle(
    role: Literal["core", "semantic"],
    output: Path,
    *,
    data_dir: Path | None = None,
    license_dir: Path = Path("docs/licenses"),
    bundle_version: str | None = None,
) -> BundleManifest:
    """Create a deterministic, checksummed ZIP data bundle."""
    data_dir = data_dir or data_directory()
    server_version = package_version("fortran-mcp")
    bundle_version = bundle_version or server_version
    registry = {source.id: source for source in load_registry().sources}
    payloads: dict[str, bytes] = {}
    requirements: tuple[BundleRequirement, ...] = ()
    model: str | None = None
    dimensions: int | None = None

    if role == "core":
        index = data_dir / INDEX_FILENAME
        table = "chunks"
        payloads[f"indexes/{INDEX_FILENAME}"] = _read_required(index)
    else:
        index = data_dir / SEMANTIC_INDEX_FILENAME
        table = "vectors"
        payloads[f"indexes/{SEMANTIC_INDEX_FILENAME}"] = _read_required(index)
        metadata = _semantic_metadata(index)
        try:
            model = metadata["model"]
            dimensions = int(metadata["dimensions"])
            requirements = (
                BundleRequirement(
                    role="core",
                    lexical_index_sha256=metadata["lexical_index_sha256"],
                ),
            )
        except (KeyError, ValueError) as error:
            raise BundleError("semantic index has incomplete metadata") from error

    source_ids = _source_ids(index, table)
    unknown = set(source_ids) - registry.keys()
    if unknown:
        raise BundleError(f"index contains unknown sources: {', '.join(sorted(unknown))}")
    sources = tuple(_manifest_source(registry[source_id]) for source_id in source_ids)
    if role == "core":
        for source in sources:
            license_path = license_dir / f"{source.id}.txt"
            payloads[f"licenses/{source.id}.txt"] = _read_required(license_path)

    files = tuple(
        BundleFile(path=path, size=len(content), sha256=_sha256_bytes(content))
        for path, content in sorted(payloads.items())
    )
    identity = _sha256_bytes("\n".join(f"{item.path}:{item.sha256}" for item in files).encode())[
        :16
    ]
    manifest = BundleManifest(
        schema_version=BUNDLE_SCHEMA_VERSION,
        bundle_id=f"fortran-mcp-{role}-{identity}",
        role=role,
        bundle_version=bundle_version,
        server_compatibility=f">={server_version},<{int(server_version.split('.')[0]) + 1}.0.0",
        sources=sources,
        embedding_model=model,
        embedding_dimensions=dimensions,
        requires=requirements,
        files=files,
    )
    manifest_bytes = (json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_bytes)
        for path, content in sorted(payloads.items()):
            archive.writestr(_zip_info(path), content)
    verify_bundle(output)
    return manifest


def _read_required(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise BundleError(f"required bundle file is unavailable: {path}") from error


def verify_bundle(path: Path) -> BundleManifest:
    """Validate paths, manifest schema, declared contents, sizes, and checksums."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise BundleError("bundle contains duplicate paths")
            for name in names:
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise BundleError(f"bundle contains an unsafe path: {name}")
            manifest_path = f"{BUNDLE_ROOT}/manifest.json"
            manifest = BundleManifest.model_validate_json(archive.read(manifest_path))
            expected = {manifest_path} | {
                f"{BUNDLE_ROOT}/{record.path}" for record in manifest.files
            }
            if set(names) != expected:
                raise BundleError("bundle contents do not match its manifest")
            for record in manifest.files:
                content = archive.read(f"{BUNDLE_ROOT}/{record.path}")
                if len(content) != record.size or _sha256_bytes(content) != record.sha256:
                    raise BundleError(f"bundle file failed verification: {record.path}")
            return manifest
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        if isinstance(error, BundleError):
            raise
        raise BundleError(f"invalid bundle: {error}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify documentation data bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("role", choices=("core", "semantic"))
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--data-dir", type=Path, default=data_directory())
    build.add_argument("--license-dir", type=Path, default=Path("docs/licenses"))
    build.add_argument("--bundle-version")
    verify = subparsers.add_parser("verify")
    verify.add_argument("path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Build or verify one bundle from the command line."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_bundle(
                args.role,
                args.output,
                data_dir=args.data_dir,
                license_dir=args.license_dir,
                bundle_version=args.bundle_version,
            )
            print(f"Built {manifest.bundle_id}: {args.output}")
        else:
            manifest = verify_bundle(args.path)
            print(f"Verified {manifest.bundle_id}: {args.path}")
    except BundleError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
