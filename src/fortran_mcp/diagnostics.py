"""First-run diagnostics for the installed server and documentation data."""

import json
import platform
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from fortran_mcp.catalog import DEFAULT_CATALOG_URL
from fortran_mcp.config import SEARCH_PROVIDER_ENV, search_provider_name
from fortran_mcp.data_cli import DataStatus, data_status
from fortran_mcp.sources import StrictModel


def server_version() -> str:
    """Return the installed package version, including editable installs."""
    try:
        return version("fortran-mcp")
    except PackageNotFoundError:
        return "unknown"


class DiagnosticReport(StrictModel):
    """Machine-readable first-run and troubleshooting summary."""

    server_version: str
    python_version: str
    search_provider: str
    catalog_url: str
    data: DataStatus
    ready: bool
    actions: tuple[str, ...]


def diagnose() -> DiagnosticReport:
    """Inspect configuration and turn missing prerequisites into concrete actions."""
    status = data_status()
    actions: list[str] = []
    try:
        provider = search_provider_name()
    except ValueError:
        provider = "invalid"
        actions.append(f"Set {SEARCH_PROVIDER_ENV} to lexical, semantic, or hybrid")

    core = status.bundles[0]
    semantic = status.bundles[1]
    if not core.installed:
        actions.append("Install core data: fortran-mcp data install core")
    elif not core.valid:
        actions.append("Reinstall invalid core data: fortran-mcp data install core")

    if provider in {"semantic", "hybrid"}:
        if not status.semantic_runtime_installed:
            actions.append(
                "Install semantic support: uv tool install 'fortran-mcp[semantic]' --force"
            )
        if not semantic.installed:
            actions.append("Install semantic data: fortran-mcp data install semantic")
        elif not semantic.valid:
            actions.append("Reinstall invalid semantic data: fortran-mcp data install semantic")

    ready = status.lexical_ready and (
        provider == "lexical" or (provider in {"semantic", "hybrid"} and status.semantic_ready)
    )
    if ready:
        actions.append("Ready: configure an MCP client to launch 'fortran-mcp'")
    return DiagnosticReport(
        server_version=server_version(),
        python_version=platform.python_version(),
        search_provider=provider,
        catalog_url=DEFAULT_CATALOG_URL,
        data=status,
        ready=ready,
        actions=tuple(actions),
    )


def _print_report(report: DiagnosticReport) -> None:
    print(f"Fortran MCP: {report.server_version}")
    print(f"Python: {report.python_version}")
    print(f"Provider: {report.search_provider}")
    print(f"Data directory: {report.data.data_directory}")
    for bundle in report.data.bundles:
        state = (
            f"valid ({bundle.bundle_version}, {len(bundle.sources)} sources)"
            if bundle.valid
            else f"invalid ({bundle.error})"
            if bundle.installed
            else "not installed"
        )
        print(f"{bundle.role.title()} data: {state}")
    print(f"Ready: {'yes' if report.ready else 'no'}")
    for action in report.actions:
        print(f"Next: {action}")


def main(argv: Sequence[str] | None = None) -> None:
    """Print human- or machine-readable diagnostics."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="fortran-mcp doctor", description="Check server readiness"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = diagnose()
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        _print_report(report)
