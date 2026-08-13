"""Runtime configuration for local Fortran MCP data and providers."""

import os
import sys
from pathlib import Path

DATA_DIR_ENV = "FORTRAN_MCP_DATA_DIR"
SEARCH_PROVIDER_ENV = "FORTRAN_MCP_SEARCH_PROVIDER"
SEARCH_PROVIDERS = frozenset({"lexical", "semantic", "hybrid"})


def user_data_directory() -> Path:
    """Return the platform-appropriate per-user data directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "fortran-mcp"
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        return Path(root) / "fortran-mcp" if root else Path.home() / "fortran-mcp"
    root = os.environ.get("XDG_DATA_HOME")
    return (Path(root) if root else Path.home() / ".local" / "share") / "fortran-mcp"


def data_directory() -> Path:
    """Return the configured data directory without creating it."""
    configured = os.environ.get(DATA_DIR_ENV)
    return Path(configured).expanduser() if configured else user_data_directory()


def search_provider_name() -> str:
    """Return the configured retrieval provider name."""
    configured = os.environ.get(SEARCH_PROVIDER_ENV, "lexical").casefold()
    if configured not in SEARCH_PROVIDERS:
        choices = ", ".join(sorted(SEARCH_PROVIDERS))
        raise ValueError(f"{SEARCH_PROVIDER_ENV} must be one of: {choices}")
    return configured
