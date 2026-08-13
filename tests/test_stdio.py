"""End-to-end MCP test over a real stdio subprocess."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import build_index


def _prepare_index(data_dir: Path) -> None:
    chunk = DocumentChunk(
        id="a" * 32,
        source_id="fpm-0.13.0-docs",
        revision="5097350c24ea7b5ceec233714f5a2604f79d0c02",
        path="pages/how-to/compute-pi-openmp.md",
        headings=("Computing PI with OpenMP", "Using OpenMP as a dependency"),
        line_start=17,
        line_end=29,
        text='Add the OpenMP metapackage with `dependencies.openmp = "*"`.',
        sha256="b" * 64,
    )
    chunk_dir = data_dir / "chunks"
    chunk_dir.mkdir(parents=True)
    (chunk_dir / "fpm-0.13.0-docs.jsonl").write_text(
        json.dumps(chunk.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    build_index(data_dir)


async def _exercise_server(working_directory: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fortran_mcp.server"],
        cwd=working_directory,
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

    assert initialized.server_info.name == "Fortran MCP"
    assert [tool.name for tool in tools.tools] == ["search_fortran_docs"]
    assert [str(resource.uri) for resource in resources.resources] == ["fortran-docs://sources"]
    assert len(templates.resource_templates) == 2
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["result"][0]["chunk_id"] == "a" * 32


def test_stdio_server_round_trip(tmp_path: Path) -> None:
    _prepare_index(tmp_path / "data")

    asyncio.run(_exercise_server(tmp_path))
