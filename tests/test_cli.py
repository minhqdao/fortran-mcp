"""Tests for the unified Fortran MCP command line."""

from typing import Any

from fortran_mcp.cli import main


def test_cli_preserves_no_argument_stdio_behavior(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("fortran_mcp.cli.server_main", lambda args: calls.append(list(args)))

    main([])

    assert calls == [[]]


def test_cli_routes_data_subcommands(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("fortran_mcp.cli.data_cli.main", lambda args: calls.append(list(args)))

    main(["data", "status", "--json"])

    assert calls == [["status", "--json"]]
