"""End-to-end MCP test over a real stdio subprocess."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .mcp_fixtures import assert_server_contract, prepare_index


async def _exercise_server(working_directory: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fortran_mcp.server"],
        cwd=working_directory,
        env={**os.environ, "FORTRAN_MCP_DATA_DIR": str(working_directory / "data")},
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        resources = await session.list_resources()
        templates = await session.list_resource_templates()
        result = await session.call_tool(
            "search_fortran_docs",
            {"query": "OpenMP dependency", "limit": 1},
        )

    assert_server_contract(initialized, tools, resources, templates, result)


def test_stdio_server_round_trip(tmp_path: Path) -> None:
    prepare_index(tmp_path / "data")

    asyncio.run(_exercise_server(tmp_path))
