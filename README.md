# Fortran MCP

Fortran MCP brings standard specifications, compiler manuals, ecosystem tooling, dialect variations, and refactoring guides directly to your AI tools.

It gives LLM assistants a structured way to query everything from modern ISO standards to historical compiler documentation, helping you write modern Fortran or migrate legacy codebases with grounded context.

## Development

Prerequisites: Git and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/minhqdao/fortran-mcp.git
cd fortran-mcp
uv sync
uv run fortran-mcp
```

`uv sync` creates `.venv` and installs the locked runtime and development dependencies. The
server uses the standard input/output transport by default. Run the quality checks with:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Ingestion

Fetch an approved documentation source by its registry ID:

```bash
uv run fortran-mcp-ingest fpm-0.13.0-docs
```

The command writes immutable source files and a checksum record below the ignored `data/`
directory. It refuses to overwrite an existing ingestion.

Build citation-preserving document chunks after ingestion:

```bash
uv run fortran-mcp-build fpm-0.13.0-docs
```

## Planned sources

- ISO Fortran standards and corrigenda
- Vendor compiler documentation and language extensions
- Fortran Package Manager and Fortran Standard Library documentation
- C interoperability and OpenMP references
- Dialect, compatibility, modernization, and migration guides

Source licensing and redistribution terms will be recorded before documents enter the library.
The reviewed source inventory lives in [`docs/sources.toml`](docs/sources.toml); its policy is
described in [`docs/README.md`](docs/README.md).

## License

The server software is available under the [MIT License](LICENSE). Ingested documentation retains its
original copyright and license.
