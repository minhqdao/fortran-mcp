"""Smoke tests for the MCP server."""

from fortran_mcp.server import mcp


def test_server_has_expected_name() -> None:
    assert mcp.name == "Fortran MCP"
