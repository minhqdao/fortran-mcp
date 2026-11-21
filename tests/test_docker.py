"""Opt-in end-to-end tests for a built Docker image.

Build the image, then run these tests against it:

    docker build -t fortran-mcp .
    FORTRAN_MCP_DOCKER_IMAGE=fortran-mcp uv run pytest tests/test_docker.py
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

IMAGE = os.environ.get("FORTRAN_MCP_DOCKER_IMAGE", "")

pytestmark = pytest.mark.skipif(
    not IMAGE or shutil.which("docker") is None,
    reason="set FORTRAN_MCP_DOCKER_IMAGE to a built image to run Docker tests",
)

SUPPORTED_QUERY = "How do I add OpenMP as a dependency in fpm?"
# A reviewed negative benchmark case: the corpus does not cover it.
UNSUPPORTED_QUERY = "CUDA Fortran unified memory"
TIMEOUT = 60.0


def _docker(*arguments: str, timeout: float = 120) -> str:
    completed = subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True, timeout=timeout
    )
    return completed.stdout


def _results(result: mcp_types.CallToolResult) -> list[dict[str, Any]]:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    results: list[dict[str, Any]] = result.structured_content["result"]
    return results


async def _assert_search_round_trip(session: ClientSession, provider: str) -> None:
    initialized = await session.initialize()
    assert initialized.server_info.name == "Fortran MCP"
    tools = await session.list_tools()
    assert [tool.name for tool in tools.tools] == ["search_fortran_docs"]

    found = _results(
        await session.call_tool(
            "search_fortran_docs",
            {"query": SUPPORTED_QUERY, "limit": 3},
            read_timeout_seconds=TIMEOUT,
        )
    )
    assert found, f"{provider} search returned no passages"
    assert all(item["url"].startswith("https://") for item in found)
    assert "fpm-0.13.0-docs" in {item["source_id"] for item in found}

    chunk = await session.read_resource(f"fortran-docs://chunks/{found[0]['chunk_id']}")
    assert isinstance(chunk.contents[0], mcp_types.TextResourceContents)
    assert json.loads(chunk.contents[0].text)["chunk_id"] == found[0]["chunk_id"]

    sources = await session.read_resource("fortran-docs://sources")
    assert isinstance(sources.contents[0], mcp_types.TextResourceContents)
    assert len(json.loads(sources.contents[0].text)["sources"]) >= 23

    if provider == "hybrid":
        abstained = await session.call_tool(
            "search_fortran_docs", {"query": UNSUPPORTED_QUERY}, read_timeout_seconds=TIMEOUT
        )
        assert _results(abstained) == []


def test_image_runs_unprivileged_with_hybrid_data_ready() -> None:
    assert _docker("run", "--rm", IMAGE, "id", "-u").strip() != "0"
    report = json.loads(
        _docker("run", "--rm", "--network", "none", IMAGE, "fortran-mcp", "doctor", "--json")
    )
    assert report["search_provider"] == "hybrid"
    assert report["data"]["hybrid_ready"] is True
    bundles = {bundle["role"]: bundle for bundle in report["data"]["bundles"]}
    assert bundles["core"]["valid"] is True
    assert bundles["semantic"]["valid"] is True
    verified = _docker("run", "--rm", "--network", "none", IMAGE, "fortran-mcp", "data", "verify")
    assert "core" in verified
    assert "semantic" in verified
    licenses = _docker("run", "--rm", IMAGE, "ls", "/opt/fortran-mcp/data/licenses").split()
    assert "gfortran-16.2.0-manual.txt" in licenses


@pytest.mark.parametrize("provider", ["hybrid", "semantic", "lexical"])
def test_stdio_server_searches_offline_on_read_only_root(provider: str) -> None:
    parameters = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--env",
            f"FORTRAN_MCP_SEARCH_PROVIDER={provider}",
            IMAGE,
            "fortran-mcp",
        ],
    )

    async def exercise() -> None:
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await _assert_search_round_trip(session, provider)

    asyncio.run(exercise())


@pytest.fixture
def http_container() -> Iterator[str]:
    container = _docker(
        "run",
        "--detach",
        "--rm",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--publish",
        "127.0.0.1::1957",
        IMAGE,
    ).strip()
    try:
        deadline = time.monotonic() + 60
        status = ""
        while time.monotonic() < deadline:
            status = _docker("inspect", "--format", "{{.State.Health.Status}}", container).strip()
            if status == "healthy":
                break
            time.sleep(1)
        assert status == "healthy", _docker("logs", container)
        address = _docker("port", container, "1957/tcp").splitlines()[0].strip()
        yield f"http://{address}/mcp"
    finally:
        subprocess.run(["docker", "stop", container], capture_output=True, check=False)


def test_http_server_serves_hybrid_search_and_rejects_foreign_hosts(http_container: str) -> None:
    async def exercise() -> None:
        async with (
            streamable_http_client(http_container) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await _assert_search_round_trip(session, "hybrid")

    asyncio.run(exercise())

    rebinding = httpx.post(
        http_container,
        headers={
            "Host": "attacker.example",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        timeout=10,
    )
    assert rebinding.status_code == 421
