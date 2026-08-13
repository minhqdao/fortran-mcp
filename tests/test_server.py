"""Smoke tests for the MCP server."""

import asyncio
from collections.abc import Iterable
from typing import Any, cast

from fortran_mcp.server import mcp


def test_server_has_expected_name() -> None:
    assert mcp.name == "Fortran MCP"


def test_server_exposes_documentation_search() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["search_fortran_docs"]


def test_server_exposes_source_and_chunk_resources() -> None:
    resources = asyncio.run(mcp.list_resources())
    templates = asyncio.run(mcp.list_resource_templates())

    assert [str(resource.uri) for resource in resources] == ["fortran-docs://sources"]
    assert {str(template.uri_template) for template in templates} == {
        "fortran-docs://chunks/{chunk_id}",
        "fortran-docs://sources/{source_id}",
    }


def test_sources_resource_contains_registered_version() -> None:
    contents = asyncio.run(mcp.read_resource("fortran-docs://sources"))
    items = list(cast("Iterable[Any]", contents))

    assert '"version": "0.13.0"' in items[0].content
