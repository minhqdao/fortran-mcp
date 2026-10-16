"""Install, inspect, and verify user-facing documentation data."""

import argparse
import hashlib
import importlib.util
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError

from fortran_mcp.bundle import BundleError, BundleManifest, install_bundle
from fortran_mcp.catalog import DEFAULT_CATALOG_URL, CatalogError, install_from_catalog
from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import RUNTIME_HINT, SEMANTIC_INDEX_FILENAME
from fortran_mcp.sources import StrictModel

Role = Literal["core", "semantic"]

_ROLE_INDEXES: dict[Role, str] = {"core": INDEX_FILENAME, "semantic": SEMANTIC_INDEX_FILENAME}


class InstalledBundle(StrictModel):
    """Status of one installed data role."""

    role: Role
    installed: bool
    valid: bool
    bundle_id: str | None = None
    data_version: str | None = None
    sources: tuple[str, ...] = ()
    size: int = Field(ge=0)
    error: str | None = None


class DataStatus(StrictModel):
    """Complete local data and retrieval readiness report."""

    data_directory: str
    bundles: tuple[InstalledBundle, ...]
    lexical_ready: bool
    semantic_runtime_installed: bool
    semantic_ready: bool
    hybrid_ready: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _installed_path(data_dir: Path, bundled_path: str) -> Path:
    path = Path(bundled_path)
    return data_dir / (path.name if bundled_path.startswith("indexes/") else path)


def _summarize_error(error: OSError | ValueError) -> str:
    """Render one short clause per validation failure, without pydantic's dump."""
    if not isinstance(error, ValidationError):
        return str(error)
    clauses = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "manifest"
        clauses.append(f"{location}: {item['msg']}")
    return "; ".join(clauses)


def inspect_role(role: Role, data_dir: Path) -> InstalledBundle:
    """Inspect one installed role and verify every recorded payload."""
    manifest_path = data_dir / "manifests" / f"{role}.json"
    if not manifest_path.is_file():
        return InstalledBundle(role=role, installed=False, valid=False, size=0)
    try:
        manifest = BundleManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.role != role:
            raise ValueError("manifest role does not match its installed location")
        total = 0
        for record in manifest.files:
            installed = _installed_path(data_dir, record.path)
            if not installed.is_file():
                raise ValueError(f"installed file is missing: {record.path}")
            size = installed.stat().st_size
            if size != record.size or _sha256(installed) != record.sha256:
                raise ValueError(f"installed file failed verification: {record.path}")
            total += size
        return InstalledBundle(
            role=role,
            installed=True,
            valid=True,
            bundle_id=manifest.bundle_id,
            data_version=manifest.data_version,
            sources=tuple(source.id for source in manifest.sources),
            size=total,
        )
    except (OSError, ValueError) as error:
        return InstalledBundle(
            role=role,
            installed=True,
            valid=False,
            size=0,
            error=(
                f"installed manifest is invalid: {manifest_path} "
                f"({_summarize_error(error)}); "
                f"run 'fortran-mcp data remove {role} --data-dir {data_dir}' and reinstall"
            ),
        )


def data_status(data_dir: Path | None = None) -> DataStatus:
    """Return installed bundle integrity and provider readiness."""
    data_dir = data_dir or data_directory()
    core = inspect_role("core", data_dir)
    semantic = inspect_role("semantic", data_dir)
    semantic_runtime = importlib.util.find_spec("fastembed") is not None
    lexical_ready = core.valid and (data_dir / INDEX_FILENAME).is_file()
    semantic_ready = (
        lexical_ready
        and semantic.valid
        and semantic_runtime
        and (data_dir / SEMANTIC_INDEX_FILENAME).is_file()
    )
    return DataStatus(
        data_directory=str(data_dir),
        bundles=(core, semantic),
        lexical_ready=lexical_ready,
        semantic_runtime_installed=semantic_runtime,
        semantic_ready=semantic_ready,
        hybrid_ready=semantic_ready,
    )


def _role_files(data_dir: Path, role: Role) -> tuple[Path, ...]:
    """Return files tracked by one role's installed manifest, including the manifest.

    A manifest that cannot be read or trusted still yields the manifest itself
    plus the role's index file, so removal never gets stuck on stale or foreign
    formats. The fallback paths are constants we own, never manifest content.
    """
    manifest_path = data_dir / "manifests" / f"{role}.json"
    if not manifest_path.is_file():
        return ()
    try:
        manifest = BundleManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.role != role:
            raise ValueError("manifest role does not match its installed location")
        files: set[Path] = {manifest_path}
        for record in manifest.files:
            relative = PurePosixPath(record.path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or len(relative.parts) < 2
                or relative.parts[0] not in {"indexes", "licenses"}
            ):
                raise ValueError(f"installed manifest contains an unsafe path: {record.path}")
            files.add(_installed_path(data_dir, record.path))
        return tuple(files)
    except (OSError, ValueError):
        return (manifest_path, data_dir / _ROLE_INDEXES[role])


def _managed_files(data_dir: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for role in ("core", "semantic"):
        files.update(_role_files(data_dir, role))
    return tuple(sorted(files))


def remove_data(package: Role, data_dir: Path | None = None) -> int:
    """Remove one installed data package, keeping files other packages still need."""
    data_dir = data_dir or data_directory()
    targets = set(_role_files(data_dir, package))
    keep: set[Path] = set()
    for other in ("core", "semantic"):
        if other != package:
            keep.update(_role_files(data_dir, other))
    files = sorted(targets - keep)
    for path in files:
        path.unlink(missing_ok=True)
    for directory in (data_dir / "licenses", data_dir / "manifests", data_dir):
        with suppress(OSError):
            directory.rmdir()
    return len(files)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fortran-mcp data", description="Manage documentation data"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install")
    install.add_argument("role", choices=("core", "semantic"))
    origin = install.add_mutually_exclusive_group()
    origin.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_URL,
        help="local catalog path or HTTPS URL",
    )
    origin.add_argument(
        "--bundle",
        default=None,
        help="local bundle path or explicit HTTPS URL (instead of a catalog)",
    )
    install.add_argument("--data-dir", type=Path, default=data_directory())
    verify = subparsers.add_parser("verify")
    verify.add_argument("--data-dir", type=Path, default=data_directory())
    remove = subparsers.add_parser("remove")
    remove.add_argument("package", choices=("core", "semantic"))
    remove.add_argument("--data-dir", type=Path, default=data_directory())
    remove.add_argument("--yes", action="store_true", help="remove without confirmation")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run user-facing data management commands."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            if args.bundle is not None:
                manifest = install_bundle(
                    args.bundle, data_dir=args.data_dir, expected_role=args.role
                )
            else:
                manifest = install_from_catalog(args.role, args.catalog, data_dir=args.data_dir)
            print(f"Installed {manifest.bundle_id} into {args.data_dir}")
            if manifest.role == "semantic" and importlib.util.find_spec("fastembed") is None:
                print(f"Note: {RUNTIME_HINT}")
            return
        status = data_status(args.data_dir)
        if args.command == "remove":
            target = next(bundle for bundle in status.bundles if bundle.role == args.package)
            if not target.installed:
                parser.error(f"the {args.package} data package is not installed")
            if args.package == "core" and status.bundles[1].installed:
                parser.error("remove the semantic data package first")
            if not args.yes:
                try:
                    answer = input(
                        f"Remove the {args.package} data package from {args.data_dir}? [y/N] "
                    )
                except EOFError:
                    answer = ""
                if answer.casefold() not in {"y", "yes"}:
                    print("Removal cancelled")
                    return
            removed = remove_data(args.package, args.data_dir)
            print(f"Removed the {args.package} data package ({removed} files)")
            return
        if not any(bundle.installed for bundle in status.bundles):
            print("No data packages are installed")
            return
        invalid = [bundle for bundle in status.bundles if bundle.installed and not bundle.valid]
        if invalid:
            details = "; ".join(f"{bundle.role}: {bundle.error}" for bundle in invalid)
            parser.error(f"installed data package verification failed: {details}")
        print("Installed data packages verified")
    except (BundleError, CatalogError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
