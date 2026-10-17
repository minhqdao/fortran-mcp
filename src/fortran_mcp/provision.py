"""Install documentation data automatically when the server starts without any."""

import importlib.util
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
from fortran_mcp.config import data_directory, search_provider_name
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import RUNTIME_HINT, SEMANTIC_INDEX_FILENAME

AUTO_INSTALL_ENV = "FORTRAN_MCP_AUTO_INSTALL"
CATALOG_ENV = "FORTRAN_MCP_CATALOG"

_INSTALL_HINT = (
    "Install manually with:\n  fortran-mcp data install core\n  fortran-mcp data install semantic"
)


class ProvisionResult(Enum):
    """Startup provisioning outcome; SKIPPED and FAILED stop the server cleanly."""

    DATA_PRESENT = "data-present"
    OPTED_OUT = "opted-out"
    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


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
    if "semantic" in roles and not _semantic_runtime_available():
        # Explicit human choices reach here despite a missing runtime (automatic
        # paths are refused earlier); warn instead of blocking.
        message(f"Note: {RUNTIME_HINT}")
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


def _required_roles(provider: str) -> tuple[BundleRole, ...]:
    """Return the data packages a search provider needs to run."""
    if provider in {"semantic", "hybrid"}:
        return ("core", "semantic")
    return ("core",)


def _semantic_runtime_available() -> bool:
    """Return whether the optional embedding runtime is importable."""
    return importlib.util.find_spec("fastembed") is not None


def _semantic_manifest_present(data_dir: Path) -> bool:
    """Return whether a semantic bundle manifest is installed."""
    return (data_dir / "manifests" / "semantic.json").is_file()


def _offer_top_up(
    provider: str,
    catalog_location: CatalogLocation,
    data_dir: Path,
    message: Callable[[str], None],
    prompt: Callable[[str], str],
) -> ProvisionResult:
    """Ask an interactive user to download the missing semantic package."""
    message(
        f"The {provider} search provider needs the semantic data package, which is not installed."
    )
    try:
        answer = prompt("Download it now? [y/N] ").strip().casefold()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        message("No data will be downloaded.")
        message(_INSTALL_HINT)
        return ProvisionResult.SKIPPED
    ok = _install_roles(("semantic",), catalog_location, data_dir, message)
    return ProvisionResult.INSTALLED if ok else ProvisionResult.FAILED


def _catalog_location() -> CatalogLocation:
    return os.environ.get(CATALOG_ENV, "").strip() or DEFAULT_CATALOG_URL


def offer_data_install(
    *,
    data_dir: Path | None = None,
    catalog_location: CatalogLocation | None = None,
    interactive: bool,
    prompt: Callable[[str], str] = input,
    message: Callable[[str], None] = _stderr,
) -> ProvisionResult:
    """Install the data packages the configured provider needs when they are missing.

    Terminal sessions are informed that no data exists and choose between core, core
    plus semantic, and skipping; the network is only touched after a choice. MCP
    clients launch the server without a console, so those sessions download every
    package the configured search provider needs unless FORTRAN_MCP_AUTO_INSTALL
    disables it. The catalog defaults to the project release and can be overridden
    with FORTRAN_MCP_CATALOG.
    """
    data_dir = data_dir or data_directory()
    catalog_location = catalog_location or _catalog_location()
    try:
        provider = search_provider_name()
    except ValueError as error:
        message(str(error))
        return ProvisionResult.FAILED
    if provider in {"semantic", "hybrid"} and not _semantic_runtime_available():
        message(RUNTIME_HINT)
        return ProvisionResult.FAILED
    required = _required_roles(provider)
    if not any_data_present(data_dir):
        if not interactive:
            if not _auto_install_enabled():
                message("Automatic data download is disabled.")
                message(_INSTALL_HINT)
                return ProvisionResult.OPTED_OUT
            installed = _install_roles(required, catalog_location, data_dir, message)
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
        if not installed:
            return ProvisionResult.FAILED
        if "semantic" in required and not _semantic_manifest_present(data_dir):
            return _offer_top_up(provider, catalog_location, data_dir, message, prompt)
        return ProvisionResult.INSTALLED
    if (
        "semantic" in required
        and (data_dir / "manifests" / "core.json").is_file()
        and not _semantic_manifest_present(data_dir)
    ):
        if interactive:
            return _offer_top_up(provider, catalog_location, data_dir, message, prompt)
        if not _auto_install_enabled():
            message("Automatic data download is disabled.")
            message(_INSTALL_HINT)
            return ProvisionResult.OPTED_OUT
        installed = _install_roles(("semantic",), catalog_location, data_dir, message)
        return ProvisionResult.INSTALLED if installed else ProvisionResult.FAILED
    # Satisfied installs, custom indexes without manifests, and exotic partial
    # states are all left untouched.
    return ProvisionResult.DATA_PRESENT
