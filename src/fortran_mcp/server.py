"""MCP server entry point."""

from mcp.server import MCPServer

mcp = MCPServer(
    "Fortran MCP",
    instructions="Authoritative documentation for modern and legacy Fortran development.",
)


def main() -> None:
    """Run the server over the standard input/output transport."""
    mcp.run()


if __name__ == "__main__":
    main()
