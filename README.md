# Fortran MCP

[![CI](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fortran-mcp.svg)](https://pypi.org/project/fortran-mcp/)
[![MCP](https://img.shields.io/badge/MCP-2.0-2F4F8G?labelColor=1a1a2e&color=0f4c81)](https://spec.modelcontextprotocol.io/)
[![RAG](https://img.shields.io/badge/RAG-cited%20retrieval-0e7c7b)](https://github.com/minhqdao/fortran-mcp)
[![Search](https://img.shields.io/badge/search-lexical%20+%20semantic%20+%20hybrid-0f4c81)](https://github.com/minhqdao/fortran-mcp/blob/main/benchmarks/results/)
[![Sources](https://img.shields.io/badge/sources-23-c88603?logo=gitbook&logoColor=white)](https://github.com/minhqdao/fortran-mcp/blob/main/docs/sources.toml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/minhqdao/fortran-mcp/blob/main/LICENSE)

Use Fortran MCP to improve AI-assisted Fortran development with cited documentation on language features, compiler behavior, build systems, and the wider ecosystem.

It supports lexical search (matching words), semantic search (matching meaning), and hybrid search (combining both), returning relevant passages with source attribution, version information, and links to the original documentation.

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install fortran-mcp
```

Semantic and hybrid search require additional dependencies:

```bash
uv tool install "fortran-mcp[semantic]"
```

Data bundles are installed automatically on first run. You can also install them beforehand to avoid an initial delay:

```bash
fortran-mcp data install core       # for lexical search
fortran-mcp data install semantic   # for semantic and hybrid search
```

Check installation:

```bash
fortran-mcp doctor
```

## Client Setup

<details>
<summary>Claude Code</summary>

Use lexical search (default):

```bash
claude mcp add --scope user fortran-mcp -- fortran-mcp
```

Use semantic search:

```bash
claude mcp add --scope user fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
claude mcp add --scope user fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

To change the search mode, remove the existing entry first:

```bash
claude mcp remove --scope user fortran-mcp
```

</details>

<details>
<summary>Codex</summary>

Use lexical search (default):

```bash
codex mcp add fortran-mcp -- fortran-mcp
```

Use semantic search:

```bash
codex mcp add fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
codex mcp add fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

</details>

<details>
<summary>OpenCode</summary>

Use lexical search (default):

```bash
opencode mcp add fortran-mcp --global -- fortran-mcp
```

Use semantic search:

```bash
opencode mcp add fortran-mcp --global --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
opencode mcp add fortran-mcp --global --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

</details>

## Command reference

| Command                               | Description                                                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `fortran-mcp`                         | Start the stdio MCP server.                                                                                                     |
| `fortran-mcp serve`                   | Start the HTTP server (`--host`, `--port`, `--path`, `--allowed-host`).                                                         |
| `fortran-mcp doctor`                  | Show configuration and installed data. Use `--json` for machine-readable output.                                                |
| `fortran-mcp data install <package>`  | Download and install `core` or `semantic` from the release catalog or a local bundle (`--catalog`, `--bundle`, `--data-dir`).   |
| `fortran-mcp data remove <package>`   | Remove an installed `core` or `semantic` package (`--data-dir`).                                                                |
| `fortran-mcp data verify`             | Verify installed data packages (`--data-dir`).                                                                                  |
| `fortran-mcp source list`             | List reviewed sources with versions and provenance. Use `--json` for machine-readable output.                                   |
| `fortran-mcp source sync <source>...` | Download reviewed sources and rebuild their chunks and lexical index. Accepts one or more source IDs or `--all` (`--data-dir`). |

## Development

```bash
git clone https://github.com/minhqdao/fortran-mcp.git
cd fortran-mcp
uv sync
uv run fortran-mcp
```

The server uses stdio by default. To test the Streamable HTTP transport, run:

```bash
uv run fortran-mcp serve
```

The endpoint is available at `http://127.0.0.1:1957/mcp`.

Run quality checks with:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Sources

The documentation collection is curated, not exhaustive. New sources should address gaps in existing coverage or improve retrieval quality on realistic benchmark questions, while justifying their storage costs and impact on search results. All material must be legally redistributable.

Public availability does not imply permission to redistribute documentation, particularly standards, books, and vendor manuals.

The source inventory is maintained in [`docs/sources.toml`](docs/sources.toml).

## Publishing

### Fortran MCP Releases

Before publishing `fortran-mcp` to PyPI, bump the version in `pyproject.toml` and update `CHANGELOG.md`. Commit, push to `main`, and wait for CI to turn green. Then create and push a matching `v<version>` tag to trigger the `Publish PyPI` workflow (`.github/workflows/publish-pypi.yml`) which builds and publishes the `fortran-mcp` package.

### Data Bundle Releases

To publish data packages to GitHub Releases, make sure all commits are pushed to `main` and CI is
green. Then manually trigger the `Publish Data` GitHub Actions workflow
(`.github/workflows/publish-data.yml`) and enter a `data_version` in the
`YYYY.MM.N` format, where `N` is a sequential number for releases within the same
month. The workflow rebuilds the corpus from `docs/sources.toml` and publishes both
the `core` and `semantic` bundles under the same version.

## License

The server software is available under the
[MIT License](LICENSE).

[Sources](docs/sources.toml) retain their
original copyrights and [licenses](docs/licenses/).
