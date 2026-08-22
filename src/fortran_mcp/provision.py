"""Install documentation data automatically when the server starts without any."""

import os
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from fortran_mcp.bundle import BundleError
from fortran_mcp.catalog import (
    DEFAULT_CATALOG_URL,
    BundleRole,
    CatalogError,
    CatalogLocation,
    install_from_catalog,
)
from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME

AUTO_INSTALL_ENV = "FORTRAN_MCP_AUTO_INSTALL"

_INSTALL_HINT = (
    "Install manually with:\n"
    "  fortran-mcp data install core\n"
    "  fortran-mcp data install semantic"
)


class ProvisionResult(Enum):
    """Startup provisioning outcome; SKIPPED and FAILED stop the server cleanly."""

    DATA_PRESENT = "data-present"
    OPTED_OUT = "opted-out"
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


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


def _auto_install_enabled() -> bool:
    value = os.environ.get(AUTO_INSTALL_ENV, "1").strip().casefold()
    return value not in {"0", "false", "no"}


def _install_roles(
    roles: tuple[BundleRole, ...],
    catalog_location: CatalogLocation,
    data_dir: Path,
    message: Callable[[str], None],
) -> bool:
    try:
        for role in roles:
            message(f"Downloading {role} data...")
            manifest = install_from_catalog(role, catalog_location, data_dir=data_dir)
            message(f"Installed {manifest.bundle_id}")
    except (BundleError, CatalogError) as error:
        text = str(error)
        message(f"Download failed: {text[:1].upper()}{text[1:]}")
        message(_INSTALL_HINT)
        return False
    return True


def offer_data_install(
    *,
    data_dir: Path | None = None,
    catalog_location: CatalogLocation = DEFAULT_CATALOG_URL,
    interactive: bool,
    prompt: Callable[[str], str] = input,
    message: Callable[[str], None] = _stderr,
) -> ProvisionResult:
    """Install core data when nothing is installed yet.

    Terminal sessions are informed that no data exists and choose between core, core
    plus semantic, and skipping; the network is only touched after a choice. MCP
    clients launch the server without a console, so those sessions download the core
    bundle automatically unless FORTRAN_MCP_AUTO_INSTALL disables it.
    """
    data_dir = data_dir or data_directory()
    if any_data_present(data_dir):
        return ProvisionResult.DATA_PRESENT
    if not interactive:
        if not _auto_install_enabled():
            message("Automatic data download is disabled.")
            message(_INSTALL_HINT)
            return ProvisionResult.OPTED_OUT
        installed = _install_roles(("core",), catalog_location, data_dir, message)
        return ProvisionResult.INSTALLED if installed else ProvisionResult.FAILED
    message(
        "No data packages found. Select a package to download:\n"
        "  1) core (lexical search)\n"
        "  2) core + semantic (adds semantic and hybrid search)\n"
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
        message("No data will be downloaded.")
        message(_INSTALL_HINT)
        return ProvisionResult.SKIPPED
    installed = _install_roles(roles, catalog_location, data_dir, message)
    return ProvisionResult.INSTALLED if installed else ProvisionResult.FAILED
