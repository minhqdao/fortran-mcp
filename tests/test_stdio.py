"""End-to-end MCP test over a real stdio subprocess."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .mcp_fixtures import assert_server_contract, prepare_index
from .test_provision import _release


async def _exercise_server(working_directory: Path, *, catalog: Path | None = None) -> None:
    env = {**os.environ, "FORTRAN_MCP_DATA_DIR": str(working_directory / "data")}
    if catalog is not None:
        env["FORTRAN_MCP_CATALOG"] = str(catalog)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fortran_mcp.server"],
        cwd=working_directory,
        env=env,
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


def test_stdio_server_auto_installs_core_and_serves_search(tmp_path: Path) -> None:
    catalog = _release(tmp_path)
    data_dir = tmp_path / "data"

    asyncio.run(_exercise_server(tmp_path, catalog=catalog))

    assert (data_dir / "manifests" / "core.json").is_file()
    assert (data_dir / "fortran-mcp.db").is_file()
