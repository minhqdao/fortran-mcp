"""Smoke tests for the MCP server."""

import asyncio

from fortran_mcp.server import mcp


def test_server_has_expected_name() -> None:
    assert mcp.name == "Fortran MCP"


def test_server_exposes_documentation_search() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["search_fortran_docs"]
