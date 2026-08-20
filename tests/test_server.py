"""Smoke tests for the MCP server."""

import asyncio
from collections.abc import Iterable
from typing import Any, cast

from mcp.types import CallToolResult
from pydantic import HttpUrl

from fortran_mcp.search import SearchResult
from fortran_mcp.server import main, mcp
from fortran_mcp.sources import DocumentType, SourceAuthority


def test_server_has_expected_name() -> None:
    assert mcp.name == "Fortran MCP"
    assert "Cite each result's URL" in str(mcp.instructions)
    assert "coverage gap" in str(mcp.instructions)


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


def test_search_tool_uses_provider_contract(monkeypatch: Any) -> None:
    expected = SearchResult(
        chunk_id="a" * 32,
        score=1.0,
        source_id="test-source",
        source_title="Test source",
        document_type=DocumentType.ECOSYSTEM_GUIDE,
        authority=SourceAuthority.COMMUNITY,
        topics=("test",),
        version="1",
        revision="v1",
        path="guide.md",
        headings=("Guide",),
        line_start=1,
        line_end=2,
        text="Result",
        url=HttpUrl("https://example.com/guide"),
    )

    class FakeProvider:
        def search(
            self,
            query: str,
            *,
            limit: int = 5,
            source_id: str | None = None,
            compiler: str | None = None,
            version: str | None = None,
            fortran_version: str | None = None,
        ) -> tuple[SearchResult, ...]:
            assert (query, limit, source_id, compiler, version, fortran_version) == (
                "query",
                3,
                "test-source",
                None,
                None,
                None,
            )
            return (expected,)

        def get_chunk(self, chunk_id: str) -> SearchResult:
            assert chunk_id == expected.chunk_id
            return expected

    monkeypatch.setattr("fortran_mcp.server.search_provider", FakeProvider)
    searched = asyncio.run(
        mcp.call_tool(
            "search_fortran_docs",
            {"query": "query", "limit": 3, "source_id": "test-source"},
        )
    )
    resource = asyncio.run(mcp.read_resource(f"fortran-docs://chunks/{expected.chunk_id}"))

    tool_result = cast("CallToolResult", searched)
    assert tool_result.structured_content == {"result": [expected.model_dump(mode="json")]}
    assert expected.chunk_id in next(iter(cast("Iterable[Any]", resource))).content


def test_search_tool_filters_source_applicability(monkeypatch: Any) -> None:
    ecosystem = SearchResult(
        chunk_id="b" * 32,
        score=1,
        source_id="fpm",
        source_title="fpm",
        document_type=DocumentType.ECOSYSTEM_GUIDE,
        authority=SourceAuthority.OFFICIAL,
        topics=("build-system",),
        compilers=("gfortran",),
        fortran_versions=("Fortran 2018",),
        version="1",
        revision="v1",
        path="guide.md",
        headings=("Guide",),
        line_start=1,
        line_end=1,
        text="Build",
        url=HttpUrl("https://example.com/build"),
    )

    class FakeProvider:
        def search(
            self,
            query: str,
            *,
            limit: int = 5,
            source_id: str | None = None,
            compiler: str | None = None,
            version: str | None = None,
            fortran_version: str | None = None,
        ) -> tuple[SearchResult, ...]:
            assert limit == 20
            assert (compiler, version, fortran_version) == (
                "gfortran",
                "1",
                "Fortran 2018",
            )
            return (ecosystem,)

        def get_chunk(self, chunk_id: str) -> SearchResult:
            return ecosystem

    monkeypatch.setattr("fortran_mcp.server.search_provider", FakeProvider)
    searched = asyncio.run(
        mcp.call_tool(
            "search_fortran_docs",
            {
                "query": "build",
                "topic": "build-system",
                "compiler": "gfortran",
                "version": "1",
                "fortran_version": "Fortran 2018",
            },
        )
    )

    tool_result = cast("CallToolResult", searched)
    assert tool_result.structured_content == {"result": [ecosystem.model_dump(mode="json")]}


def test_server_defaults_to_stdio(monkeypatch: Any) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(mcp, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    main([])

    assert calls == [((), {})]


def test_server_configures_streamable_http_security(monkeypatch: Any) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(mcp, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    main(
        [
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--path",
            "/fortran",
            "--allowed-host",
            "docs.example.com",
        ]
    )

    args, kwargs = calls[0]
    assert args == ("streamable-http",)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9000
    assert kwargs["streamable_http_path"] == "/fortran"
    assert kwargs["transport_security"].enable_dns_rebinding_protection is True
    assert kwargs["transport_security"].allowed_hosts == ["docs.example.com"]
