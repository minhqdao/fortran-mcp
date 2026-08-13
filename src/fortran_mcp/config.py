"""Runtime configuration for local Fortran MCP data and providers."""

import os
from pathlib import Path

DATA_DIR_ENV = "FORTRAN_MCP_DATA_DIR"
DEFAULT_DATA_DIR = Path("data")


def data_directory() -> Path:
    """Return the configured data directory without creating it."""
    configured = os.environ.get(DATA_DIR_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_DATA_DIR
