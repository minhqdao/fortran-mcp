"""Unified user-facing command line for Fortran MCP."""

import sys
from collections.abc import Sequence

from fortran_mcp import data_cli
from fortran_mcp.server import main as server_main


def main(argv: Sequence[str] | None = None) -> None:
    """Run data management commands or start the MCP server."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "data":
        data_cli.main(arguments[1:])
    else:
        server_main(arguments)


if __name__ == "__main__":
    main()
