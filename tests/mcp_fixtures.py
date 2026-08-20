"""Shared setup and contract assertions for end-to-end MCP server tests."""

import json
from pathlib import Path

from mcp import types as mcp_types

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import build_index

OMP_CHUNK_ID = "a" * 32


def prepare_index(data_dir: Path) -> None:
    """Write a single searchable OpenMP chunk and build the lexical index."""
    chunk = DocumentChunk(
        id=OMP_CHUNK_ID,
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


def assert_server_contract(
    initialized: mcp_types.InitializeResult,
    tools: mcp_types.ListToolsResult,
    resources: mcp_types.ListResourcesResult,
    templates: mcp_types.ListResourceTemplatesResult,
    result: mcp_types.CallToolResult,
) -> None:
    """Assert the expected MCP surface and search behavior."""
    assert initialized.server_info.name == "Fortran MCP"
    assert [tool.name for tool in tools.tools] == ["search_fortran_docs"]
    assert [str(resource.uri) for resource in resources.resources] == ["fortran-docs://sources"]
    assert len(templates.resource_templates) == 2
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["result"][0]["chunk_id"] == OMP_CHUNK_ID
