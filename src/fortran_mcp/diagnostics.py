"""Installation diagnostics for the installed server and documentation data."""

import json
import platform
import sqlite3
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fortran_mcp.catalog import DEFAULT_CATALOG_URL
from fortran_mcp.config import search_provider_name
from fortran_mcp.data_cli import DataStatus, data_status
from fortran_mcp.search import INDEX_FILENAME
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME
from fortran_mcp.sources import StrictModel


def server_version() -> str:
    """Return the installed package version, including editable installs."""
    try:
        return version("fortran-mcp")
    except PackageNotFoundError:
        return "unknown"


class DiagnosticReport(StrictModel):
    """Machine-readable installation and data summary."""

    server_version: str
    python_version: str
    search_provider: str
    catalog_url: str
    data: DataStatus


def diagnose() -> DiagnosticReport:
    """Inspect configuration and installed data without prescribing actions."""
    status = data_status()
    try:
        provider = search_provider_name()
    except ValueError:
        provider = "invalid"
    return DiagnosticReport(
        server_version=server_version(),
        python_version=platform.python_version(),
        search_provider=provider,
        catalog_url=DEFAULT_CATALOG_URL,
        data=status,
    )


def _chunk_count(index: Path) -> int | None:
    with suppress(sqlite3.Error), sqlite3.connect(f"file:{index}?mode=ro", uri=True) as database:
        return int(database.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    return None


def _data_labels(data_dir: Path, status: DataStatus) -> tuple[str, ...]:
    labels = []
    for bundle in status.bundles:
        if not bundle.installed:
            continue
        if bundle.valid:
            labels.append(f"{bundle.role} {bundle.data_version} ({len(bundle.sources)} sources)")
        else:
            labels.append(f"{bundle.role} invalid ({bundle.error})")
    if not labels:
        if (data_dir / INDEX_FILENAME).is_file():
            count = _chunk_count(data_dir / INDEX_FILENAME)
            labels.append(
                f"custom lexical index ({count} chunks)"
                if count is not None
                else "custom lexical index"
            )
        if (data_dir / SEMANTIC_INDEX_FILENAME).is_file():
            labels.append("custom semantic index")
    return tuple(labels)


def _print_report(report: DiagnosticReport) -> None:
    print(f"Fortran MCP: {report.server_version}")
    print(f"Python: {report.python_version}")
    print(f"Provider: {report.search_provider}")
    print(f"Data directory: {report.data.data_directory}")
    labels = _data_labels(Path(report.data.data_directory), report.data)
    if labels:
        print("Data:")
        for label in labels:
            print(f"  - {label}")
    else:
        print("Data: none")


def main(argv: Sequence[str] | None = None) -> None:
    """Print human- or machine-readable diagnostics."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="fortran-mcp doctor", description="Check the Fortran MCP installation"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = diagnose()
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        _print_report(report)


if __name__ == "__main__":
    main()
