"""Unified user-facing command line for Fortran MCP."""

import argparse
import sys
from collections.abc import Sequence

from fortran_mcp import data_cli, diagnostics, source_cli


def _port(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def _path(value: str) -> str:
    if not value.startswith("/"):
        raise argparse.ArgumentTypeError("HTTP path must start with /")
    return value


def _serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fortran-mcp serve", description="Serve Fortran MCP over Streamable HTTP"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=1957)
    parser.add_argument("--path", type=_path, default="/mcp")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="accepted HTTP Host header; repeat for multiple hosts",
    )
    return parser


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
        options = _serve_parser().parse_args(arguments[1:])
        from fortran_mcp.server import serve_http

        serve_http(
            host=options.host,
            port=options.port,
            path=options.path,
            allowed_hosts=options.allowed_host,
        )
        return
    if arguments:
        _help_parser().error(f"unknown command: {arguments[0]}")
    from fortran_mcp.server import serve_stdio

    serve_stdio()


if __name__ == "__main__":
    main()
