"""Tests for the unified Fortran MCP command line."""

from typing import Any

from pytest import CaptureFixture

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
        "fortran_mcp.cli.server_main",
        lambda _args: (_ for _ in ()).throw(AssertionError("server started")),
    )

    main(["--version"])

    assert capsys.readouterr().out.strip() == "1.2.3"


def test_cli_routes_doctor_source_and_explicit_serve(monkeypatch: Any) -> None:
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        "fortran_mcp.cli.diagnostics.main",
        lambda args: calls.append(("doctor", list(args))),
    )
    monkeypatch.setattr(
        "fortran_mcp.cli.source_cli.main",
        lambda args: calls.append(("source", list(args))),
    )
    monkeypatch.setattr(
        "fortran_mcp.cli.server_main",
        lambda args: calls.append(("serve", list(args))),
    )

    main(["doctor", "--json"])
    main(["source", "list"])
    main(["serve", "--transport", "streamable-http"])

    assert calls == [
        ("doctor", ["--json"]),
        ("source", ["list"]),
        ("serve", ["--transport", "streamable-http"]),
    ]
