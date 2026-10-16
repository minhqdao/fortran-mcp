"""Build and verify reproducible documentation data bundles."""

import argparse
import gc
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from collections.abc import Sequence
from importlib.metadata import version as package_version
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, model_validator

from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME
from fortran_mcp.sources import Source, StrictModel, load_registry

BUNDLE_SCHEMA_VERSION: Literal[2] = 2
BUNDLE_ROOT = "fortran-mcp-bundle"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
DOWNLOAD_LIMIT = 2 * 1024 * 1024 * 1024
MANIFEST_LIMIT = 1024 * 1024


class BundleError(RuntimeError):
    """Raised when a bundle cannot be built or verified."""


class BundleFile(StrictModel):
    """Integrity record for one bundled payload file."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def path_is_safe_payload(self) -> "BundleFile":
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 2
            or path.parts[0] not in {"indexes", "licenses"}
            or "\\" in self.path
        ):
            raise ValueError("bundle file path must be a safe index or license path")
        return self


class BundleSource(StrictModel):
    """Source provenance and licensing embedded in a bundle manifest."""

    id: str
    version: str
    revision: str
    document_type: str
    authority: str
    topics: tuple[str, ...]
    compilers: tuple[str, ...]
    fortran_versions: tuple[str, ...]
    license: str
    license_url: str


class BundleRequirement(StrictModel):
    """A required companion artifact and its exact payload checksum."""

    role: Literal["core"]
    lexical_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BundleManifest(StrictModel):
    """Stable, machine-readable contract for one data bundle."""

    schema_version: Literal[2]
    bundle_id: str
    role: Literal["core", "semantic"]
    data_version: str
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
        compilers=source.compilers,
        fortran_versions=source.fortran_versions,
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
    data_version: str,
) -> BundleManifest:
    """Create a deterministic, checksummed ZIP data bundle."""
    data_dir = data_dir or data_directory()
    server_version = package_version("fortran-mcp")
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
        data_version=data_version,
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


def _atomic_replace_temporary(temporary_path: Path, destination: Path) -> None:
    gc.collect()
    for _ in range(20):
        try:
            temporary_path.replace(destination)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05)
    raise PermissionError(f"could not replace temporary file: {temporary_path}")


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
            manifest_info = archive.getinfo(manifest_path)
            if manifest_info.file_size > MANIFEST_LIMIT:
                raise BundleError("bundle manifest exceeds the size limit")
            manifest = BundleManifest.model_validate_json(archive.read(manifest_path))
            expected = {manifest_path} | {
                f"{BUNDLE_ROOT}/{record.path}" for record in manifest.files
            }
            if set(names) != expected:
                raise BundleError("bundle contents do not match its manifest")
            if sum(record.size for record in manifest.files) > DOWNLOAD_LIMIT:
                raise BundleError("bundle payload exceeds the size limit")
            for record in manifest.files:
                member_path = f"{BUNDLE_ROOT}/{record.path}"
                if archive.getinfo(member_path).file_size != record.size:
                    raise BundleError(f"bundle file size is invalid: {record.path}")
                content = archive.read(member_path)
                if len(content) != record.size or _sha256_bytes(content) != record.sha256:
                    raise BundleError(f"bundle file failed verification: {record.path}")
            return manifest
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as error:
        if isinstance(error, BundleError):
            raise
        raise BundleError(f"invalid bundle: {error}") from error


def _download_bundle(url: str, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise BundleError("remote bundle URL must use HTTPS")
    request = Request(url, headers={"User-Agent": "fortran-mcp/0.1"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > DOWNLOAD_LIMIT:
                raise BundleError("bundle download exceeds the size limit")
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > DOWNLOAD_LIMIT:
                    raise BundleError("bundle download exceeds the size limit")
                output.write(block)
    except (OSError, ValueError) as error:
        raise BundleError(f"could not download bundle: {error}") from error


def _server_is_compatible(manifest: BundleManifest) -> None:
    current = package_version("fortran-mcp")
    try:
        compatible = Version(current) in SpecifierSet(manifest.server_compatibility)
    except (InvalidSpecifier, InvalidVersion) as error:
        raise BundleError("bundle has invalid server compatibility metadata") from error
    if not compatible:
        raise BundleError(
            f"bundle requires fortran-mcp {manifest.server_compatibility}; "
            f"installed version is {current}"
        )


def _installed_manifest(data_dir: Path, role: str) -> BundleManifest | None:
    path = data_dir / "manifests" / f"{role}.json"
    if not path.is_file():
        return None
    try:
        return BundleManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise BundleError(f"installed {role} manifest is invalid") from error


def install_bundle(source: str | Path, *, data_dir: Path | None = None) -> BundleManifest:
    """Verify and install a local or HTTPS bundle into the configured data directory."""
    data_dir = data_dir or data_directory()
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fortran-mcp-install-", dir=data_dir.parent) as temp:
        temporary = Path(temp)
        source_text = str(source)
        windows_path = (
            len(source_text) >= 3 and source_text[1] == ":" and source_text[2] in {"/", "\\"}
        )
        parsed = urlparse(source_text)
        if parsed.scheme and not windows_path:
            archive_path = temporary / "download.zip"
            _download_bundle(source_text, archive_path)
        else:
            archive_path = Path(source).expanduser()
        manifest = verify_bundle(archive_path)
        _server_is_compatible(manifest)

        if manifest.role == "semantic":
            core = _installed_manifest(data_dir, "core")
            if core is None:
                raise BundleError("install a compatible core bundle before the semantic bundle")
            core_index = next(
                (record for record in core.files if record.path == f"indexes/{INDEX_FILENAME}"),
                None,
            )
            required = manifest.requires[0] if manifest.requires else None
            if (
                core_index is None
                or required is None
                or core_index.sha256 != required.lexical_index_sha256
            ):
                raise BundleError("semantic bundle is incompatible with the installed core bundle")

        staged: list[tuple[Path, Path]] = []
        with zipfile.ZipFile(archive_path) as archive:
            for record in manifest.files:
                if record.path.startswith("indexes/"):
                    relative = Path(Path(record.path).name)
                else:
                    relative = Path(record.path)
                staged_path = temporary / "staged" / relative
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(f"{BUNDLE_ROOT}/{record.path}") as source_file,
                    staged_path.open("wb") as destination_file,
                ):
                    shutil.copyfileobj(source_file, destination_file)
                staged.append((staged_path, data_dir / relative))

        for staged_path, installed_path in staged:
            installed_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_replace_temporary(staged_path, installed_path)
        manifest_path = data_dir / "manifests" / f"{manifest.role}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_manifest = temporary / f"{manifest.role}.json"
        temporary_manifest.write_text(manifest.model_dump_json(indent=2) + "\n")
        _atomic_replace_temporary(temporary_manifest, manifest_path)
        return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify documentation data bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("role", choices=("core", "semantic"))
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--data-dir", type=Path, default=data_directory())
    build.add_argument("--license-dir", type=Path, default=Path("docs/licenses"))
    build.add_argument("--data-version", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("path", type=Path)
    install = subparsers.add_parser("install")
    install.add_argument("source", help="local bundle path or explicit HTTPS URL")
    install.add_argument("--data-dir", type=Path, default=data_directory())
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
                data_version=args.data_version,
            )
            print(f"Built {manifest.bundle_id}: {args.output}")
        elif args.command == "verify":
            manifest = verify_bundle(args.path)
            print(f"Verified {manifest.bundle_id}: {args.path}")
        else:
            manifest = install_bundle(args.source, data_dir=args.data_dir)
            print(f"Installed {manifest.bundle_id} into {args.data_dir}")
    except BundleError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
