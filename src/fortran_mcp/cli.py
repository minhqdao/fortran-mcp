"""Unified user-facing command line for Fortran MCP."""

import argparse
import sys
from collections.abc import Sequence

from fortran_mcp import data_cli, diagnostics, source_cli


def server_main(arguments: Sequence[str]) -> None:
    """Import the MCP runtime only when the server is actually started."""
    from fortran_mcp.server import main

    main(arguments)


def _help_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fortran-mcp",
        description="Serve and manage compact, cited Fortran documentation",
        epilog=(
            "With no command, starts the stdio MCP server.\n"
            "Run 'fortran-mcp COMMAND --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="store_true", help="print the installed version")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "data", "doctor", "source"),
        help="serve MCP, manage data, check readiness, or manage reviewed sources",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run data management commands or start the MCP server."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["--version"], ["-V"]):
        print(diagnostics.server_version())
        return
    if arguments in (["--help"], ["-h"]):
        _help_parser().print_help()
        return
    if arguments and arguments[0] == "data":
        data_cli.main(arguments[1:])
        return
    if arguments and arguments[0] == "doctor":
        diagnostics.main(arguments[1:])
        return
    if arguments and arguments[0] == "source":
        source_cli.main(arguments[1:])
        return
    if arguments and arguments[0] == "serve":
        arguments = arguments[1:]
        if "--transport" not in arguments:
            arguments = ["--transport", "streamable-http", *arguments]
    elif arguments:
        _help_parser().error(f"unknown command: {arguments[0]}")
    server_main(arguments)


if __name__ == "__main__":
    main()
