"""MCP server entry point."""

from mcp.server import MCPServer

from fortran_mcp.search import SearchResult, search

mcp = MCPServer(
    "Fortran MCP",
    instructions="Authoritative documentation for modern and legacy Fortran development.",
)


@mcp.tool()
def search_fortran_docs(
    query: str,
    limit: int = 5,
    source_id: str | None = None,
) -> list[SearchResult]:
    """Search authoritative Fortran documentation and return cited passages."""
    return list(search(query, limit=limit, source_id=source_id))


def main() -> None:
    """Run the server over the standard input/output transport."""
    mcp.run()


if __name__ == "__main__":
    main()
