"""Tests for the unified Fortran MCP command line."""

from typing import Any

import pytest
from pytest import CaptureFixture

from fortran_mcp.cli import main


def test_cli_preserves_no_argument_stdio_behavior(monkeypatch: Any) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        "fortran_mcp.server.serve_stdio",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    main([])

    assert calls == [((), {})]


def test_cli_routes_data_subcommands(monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("fortran_mcp.cli.data_cli.main", lambda args: calls.append(list(args)))

    main(["data", "status", "--json"])

    assert calls == [["status", "--json"]]


def test_cli_exposes_first_run_commands(capsys: CaptureFixture[str]) -> None:
    main(["--help"])

    output = capsys.readouterr().out
    assert "{serve,data,doctor,source}" in output
    assert "With no command, starts the stdio MCP server" in output


def test_cli_prints_version_without_starting_server(
    monkeypatch: Any, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr("fortran_mcp.cli.diagnostics.server_version", lambda: "1.2.3")
    monkeypatch.setattr(
        "fortran_mcp.server.serve_stdio",
        lambda: pytest.fail("server started"),
    )

    main(["--version"])

    assert capsys.readouterr().out.strip() == "1.2.3"


def test_cli_routes_doctor_source_and_serve(monkeypatch: Any) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "fortran_mcp.cli.diagnostics.main",
        lambda args: calls.append(("doctor", list(args))),
    )
    monkeypatch.setattr(
        "fortran_mcp.cli.source_cli.main",
        lambda args: calls.append(("source", list(args))),
    )
    monkeypatch.setattr(
        "fortran_mcp.server.serve_http",
        lambda **kwargs: calls.append(("serve", kwargs)),
    )

    main(["doctor", "--json"])
    main(["source", "list"])
    main(["serve", "--port", "9000", "--allowed-host", "docs.example.com"])

    assert calls == [
        ("doctor", ["--json"]),
        ("source", ["list"]),
        (
            "serve",
            {
                "host": "127.0.0.1",
                "port": 9000,
                "path": "/mcp",
                "allowed_hosts": ["docs.example.com"],
            },
        ),
    ]


def test_cli_rejects_transport_flag(monkeypatch: Any, capsys: CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "fortran_mcp.server.serve_http",
        lambda **_kwargs: pytest.fail("server started"),
    )

    with pytest.raises(SystemExit):
        main(["serve", "--transport", "stdio"])

    assert "unrecognized arguments: --transport stdio" in capsys.readouterr().err


def test_cli_rejects_http_flags_without_serve(capsys: CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--port", "9000"])

    assert "unknown command: --port" in capsys.readouterr().err
