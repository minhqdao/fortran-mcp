"""Runtime configuration for local Fortran MCP data and providers."""

import os
from pathlib import Path

DATA_DIR_ENV = "FORTRAN_MCP_DATA_DIR"
SEARCH_PROVIDER_ENV = "FORTRAN_MCP_SEARCH_PROVIDER"
DEFAULT_DATA_DIR = Path("data")
SEARCH_PROVIDERS = frozenset({"lexical", "semantic", "hybrid"})


def data_directory() -> Path:
    """Return the configured data directory without creating it."""
    configured = os.environ.get(DATA_DIR_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_DATA_DIR


def search_provider_name() -> str:
    """Return the configured retrieval provider name."""
    configured = os.environ.get(SEARCH_PROVIDER_ENV, "lexical").casefold()
    if configured not in SEARCH_PROVIDERS:
        choices = ", ".join(sorted(SEARCH_PROVIDERS))
        raise ValueError(f"{SEARCH_PROVIDER_ENV} must be one of: {choices}")
    return configured
