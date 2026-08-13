"""Install, inspect, and verify user-facing documentation data."""

import argparse
import hashlib
import importlib.util
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from fortran_mcp.bundle import BundleError, BundleManifest
from fortran_mcp.catalog import CatalogError, install_from_catalog
from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME
from fortran_mcp.sources import StrictModel

Role = Literal["core", "semantic"]


class InstalledBundle(StrictModel):
    """Status of one installed data role."""

    role: Role
    installed: bool
    valid: bool
    bundle_id: str | None = None
    bundle_version: str | None = None
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
            bundle_version=manifest.bundle_version,
            sources=tuple(source.id for source in manifest.sources),
            size=total,
        )
    except (OSError, ValueError) as error:
        return InstalledBundle(
            role=role,
            installed=True,
            valid=False,
            size=0,
            error=str(error),
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


def _print_status(status: DataStatus) -> None:
    print(f"Data directory: {status.data_directory}")
    for bundle in status.bundles:
        if not bundle.installed:
            print(f"{bundle.role}: not installed")
        elif not bundle.valid:
            print(f"{bundle.role}: invalid ({bundle.error})")
        else:
            print(
                f"{bundle.role}: {bundle.bundle_version} "
                f"({len(bundle.sources)} sources, {bundle.size} bytes)"
            )
    print(f"lexical: {'ready' if status.lexical_ready else 'unavailable'}")
    print(f"semantic: {'ready' if status.semantic_ready else 'unavailable'}")
    print(f"hybrid: {'ready' if status.hybrid_ready else 'unavailable'}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fortran-mcp data", description="Manage documentation data"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install")
    install.add_argument("role", choices=("core", "semantic"))
    install.add_argument("--catalog", required=True, type=Path)
    install.add_argument("--data-dir", type=Path, default=data_directory())
    status = subparsers.add_parser("status")
    status.add_argument("--data-dir", type=Path, default=data_directory())
    status.add_argument("--json", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--data-dir", type=Path, default=data_directory())
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run user-facing data management commands."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            manifest = install_from_catalog(args.role, args.catalog, data_dir=args.data_dir)
            print(f"Installed {manifest.bundle_id} into {args.data_dir}")
            return
        status = data_status(args.data_dir)
        if args.command == "status":
            if args.json:
                print(json.dumps(status.model_dump(mode="json"), indent=2))
            else:
                _print_status(status)
            return
        invalid = [
            bundle.role for bundle in status.bundles if bundle.installed and not bundle.valid
        ]
        if invalid:
            parser.error(f"installed bundle verification failed: {', '.join(invalid)}")
        if not any(bundle.installed for bundle in status.bundles):
            parser.error("no data bundles are installed")
        print("Installed data bundles verified")
    except (BundleError, CatalogError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
