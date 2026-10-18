"""End-to-end MCP test over a real Streamable HTTP subprocess."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .mcp_fixtures import assert_server_contract, prepare_index


def _free_port() -> int:
    """Reserve and release an ephemeral TCP port for the server to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_failure_message(process: subprocess.Popen[bytes]) -> str:
    """Describe an early-exiting server process with its captured stderr."""
    stderr = ""
    if process.stderr is not None:
        stderr = process.stderr.read().decode(errors="replace")
    return f"server exited early with rc={process.returncode}; stderr:\n{stderr}"


def _wait_for_port(
    host: str, port: int, process: subprocess.Popen[bytes], timeout: float = 15
) -> None:
    """Poll until the server accepts connections, surfacing early crashes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(_server_failure_message(process))
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server did not start on {host}:{port}")


async def _exercise_http_server(port: int) -> None:
    """Connect to the HTTP server and exercise the search tool end-to-end."""
    async with (
        streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
            read_stream,
            write_stream,
        ),
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


def test_streamable_http_server_round_trip(tmp_path: Path) -> None:
    """The server accepts MCP requests over Streamable HTTP on a dedicated port."""
    prepare_index(tmp_path / "data")
    port = _free_port()

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "fortran_mcp",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--path",
            "/mcp",
        ],
        env={**os.environ, "FORTRAN_MCP_DATA_DIR": str(tmp_path / "data")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port("127.0.0.1", port, process)
        assert process.poll() is None, _server_failure_message(process)
        asyncio.run(_exercise_http_server(port))
        assert process.poll() is None, _server_failure_message(process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
