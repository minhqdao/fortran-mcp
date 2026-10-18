"""MCP server entry point."""

import importlib.util
import json
import os
import signal
import sys
from functools import cache

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from fortran_mcp.config import search_provider_name
from fortran_mcp.search import SearchProvider, SearchResult, SQLiteSearchProvider
from fortran_mcp.sources import load_registry

mcp = MCPServer(
    "Fortran MCP",
    instructions=(
        "Search the local cited corpus before answering Fortran questions. Use source, compiler, "
        "version, or topic filters when applicability matters. Cite each result's URL and "
        "distinguish normative, official, and community guidance. If relevant passages are absent, "
        "state the coverage gap instead of inventing an answer."
    ),
)


@cache
def search_provider() -> SearchProvider:
    """Create the configured search backend."""
    provider_name = search_provider_name()
    lexical = SQLiteSearchProvider()
    if provider_name == "lexical":
        return lexical

    from fortran_mcp.semantic import RUNTIME_HINT, SemanticSearchProvider

    if importlib.util.find_spec("fastembed") is None:
        raise RuntimeError(RUNTIME_HINT)

    semantic = SemanticSearchProvider()
    if provider_name == "semantic":
        return semantic

    from fortran_mcp.hybrid import HybridSearchProvider

    return HybridSearchProvider(lexical, semantic)


@mcp.tool()
def search_fortran_docs(
    query: str,
    limit: int = 5,
    source_id: str | None = None,
    document_type: str | None = None,
    authority: str | None = None,
    topic: str | None = None,
    compiler: str | None = None,
    version: str | None = None,
    fortran_version: str | None = None,
) -> list[SearchResult]:
    """Search cited Fortran docs; use applicability filters and cite returned URLs."""
    filtered = any(value is not None for value in (document_type, authority, topic))
    results = search_provider().search(
        query,
        limit=20 if filtered else limit,
        source_id=source_id,
        compiler=compiler,
        version=version,
        fortran_version=fortran_version,
    )
    return [
        result
        for result in results
        if (document_type is None or result.document_type == document_type)
        and (authority is None or result.authority == authority)
        and (topic is None or topic in result.topics)
    ][:limit]


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
    return search_provider().get_chunk(chunk_id).model_dump_json(indent=2)


def _prepare() -> None:
    """Install any missing data packages before serving."""
    from fortran_mcp.provision import ProvisionResult, offer_data_install

    result = offer_data_install(interactive=sys.stdin.isatty())
    if result in {ProvisionResult.SKIPPED, ProvisionResult.FAILED}:
        raise SystemExit(1 if result is ProvisionResult.FAILED else 0)


def serve_stdio() -> None:
    """Serve MCP over stdio, the transport MCP clients launch."""
    _prepare()
    # anyio installs its own SIGINT handler that funnels into task cancellation,
    # which stalls on the blocked stdin reader; take over SIGINT so one Ctrl-C
    # always stops the server at once. (anyio defers when the handler is taken.)
    signal.signal(signal.SIGINT, lambda _signum, _frame: os._exit(130))
    print("Serving fortran-mcp over stdio...", file=sys.stderr)
    mcp.run()


def serve_http(*, host: str, port: int, path: str, allowed_hosts: list[str]) -> None:
    """Serve MCP over Streamable HTTP."""
    _prepare()
    mcp.run(
        "streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or [f"{host}:{port}"],
        ),
    )


if __name__ == "__main__":
    from fortran_mcp.cli import main

    main()
