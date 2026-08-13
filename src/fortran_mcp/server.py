"""MCP server entry point."""

import json

from mcp.server import MCPServer

from fortran_mcp.search import SearchResult, get_chunk, search
from fortran_mcp.sources import load_registry

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


@mcp.resource(
    "fortran-docs://sources",
    name="Fortran documentation sources",
    description="Registered documentation sources with versions and provenance",
    mime_type="application/json",
)
def documentation_sources() -> str:
    """List registered documentation sources and their provenance."""
    return json.dumps(load_registry().model_dump(mode="json"), indent=2)


@mcp.resource(
    "fortran-docs://sources/{source_id}",
    name="Fortran documentation source",
    description="Provenance for one registered documentation source",
    mime_type="application/json",
)
def documentation_source(source_id: str) -> str:
    """Return provenance for one registered documentation source."""
    source = next((item for item in load_registry().sources if item.id == source_id), None)
    if source is None:
        raise ValueError(f"unknown source ID: {source_id}")
    return source.model_dump_json(indent=2)


@mcp.resource(
    "fortran-docs://chunks/{chunk_id}",
    name="Fortran documentation chunk",
    description="An exact indexed passage with its citation",
    mime_type="application/json",
)
def documentation_chunk(chunk_id: str) -> str:
    """Return one exact indexed passage by stable chunk ID."""
    return get_chunk(chunk_id).model_dump_json(indent=2)


def main() -> None:
    """Run the server over the standard input/output transport."""
    mcp.run()


if __name__ == "__main__":
    main()
