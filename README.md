# Fortran MCP

Fortran MCP is a Model Context Protocol server for authoritative Fortran documentation. It
will make language standards, compiler manuals, ecosystem documentation, interoperability
guides, dialect references, and migration material searchable through MCP clients.

The project is in its initial development stage. Its first target is a reliable, cited
documentation retrieval layer for both modern Fortran development and legacy-code migration.

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

## Planned sources

- ISO Fortran standards and corrigenda
- Vendor compiler documentation and language extensions
- Fortran Package Manager and Fortran Standard Library documentation
- C interoperability and OpenMP references
- Dialect, compatibility, modernization, and migration guides

Source licensing and redistribution terms will be recorded before documents enter the corpus.

## License

The server software is available under the [MIT License](LICENSE). Ingested documentation retains its
original copyright and license.
