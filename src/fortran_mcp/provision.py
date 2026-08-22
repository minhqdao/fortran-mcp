"""Offer to install documentation data when the server starts without any."""

import sys
from collections.abc import Callable
from pathlib import Path

from fortran_mcp.bundle import BundleError
from fortran_mcp.catalog import (
    DEFAULT_CATALOG_URL,
    BundleRole,
    CatalogError,
    CatalogLocation,
    install_from_catalog,
    load_catalog,
)
from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME

MEBIBYTE = 1024 * 1024

_INSTALL_HINT = (
    "No Fortran documentation data is installed. Run 'fortran-mcp data install core' for "
    "lexical search, then optionally 'fortran-mcp data install semantic' to add semantic "
    "and hybrid search."
)


def _stderr(text: str) -> None:
    print(text, file=sys.stderr)


def any_data_present(data_dir: Path) -> bool:
    """Return whether any bundle manifest or local index exists in a data directory."""
    return any(
        (data_dir / relative).is_file()
        for relative in (
            Path("manifests") / "core.json",
            Path("manifests") / "semantic.json",
            INDEX_FILENAME,
            SEMANTIC_INDEX_FILENAME,
        )
    )


def offer_data_install(
    *,
    data_dir: Path | None = None,
    catalog_location: CatalogLocation = DEFAULT_CATALOG_URL,
    interactive: bool,
    prompt: Callable[[str], str] = input,
    message: Callable[[str], None] = _stderr,
) -> bool:
    """Interactively install core data when nothing is installed yet.

    The prompt only appears for interactive terminal sessions; MCP clients launch the
    server without a console, so they receive the install hint on stderr instead.
    """
    data_dir = data_dir or data_directory()
    if any_data_present(data_dir):
        return False
    if not interactive:
        message(_INSTALL_HINT)
        return False
    try:
        catalog = load_catalog(catalog_location)
    except CatalogError as error:
        message(f"{error}")
        return False
    sizes = {entry.role: entry.size for entry in catalog.bundles}
    core_mb = sizes.get("core", 0) / MEBIBYTE
    semantic_mb = sizes.get("semantic", 0) / MEBIBYTE
    message(
        "No Fortran documentation data is installed.\n"
        f"  1) core: {core_mb:.1f} MB (lexical search)\n"
        f"  2) core + semantic: {core_mb + semantic_mb:.1f} MB (adds semantic and hybrid search)\n"
        "  3) skip\n"
        "Choose [1/2/3]: "
    )
    try:
        answer = prompt("").strip()
    except EOFError:
        answer = ""
    roles: tuple[BundleRole, ...]
    if answer == "1":
        roles = ("core",)
    elif answer == "2":
        roles = ("core", "semantic")
    else:
        message(_INSTALL_HINT)
        return False
    try:
        for role in roles:
            manifest = install_from_catalog(role, catalog_location, data_dir=data_dir)
            message(f"Installed {manifest.bundle_id}")
    except (BundleError, CatalogError) as error:
        message(f"{error}")
        return False
    return True
