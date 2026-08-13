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
uv run fortran-mcp-ingest stdlib-0.8.1-docs
```

The command writes immutable source files and a checksum record below the ignored `data/`
directory. It refuses to overwrite an existing ingestion.

Set `FORTRAN_MCP_DATA_DIR` to keep generated documents and indexes elsewhere, for example on a
larger disk. All ingestion, build, index, and server commands use that location.

Build citation-preserving document chunks after ingestion:

```bash
uv run fortran-mcp-build fpm-0.13.0-docs
uv run fortran-mcp-build stdlib-0.8.1-docs
uv run fortran-mcp-index
```

The MCP server exposes `search_fortran_docs`, which returns ranked passages with the source,
version, heading hierarchy, line range, and published documentation URL.

It also exposes MCP resources for registered sources, source provenance, and exact chunks:

```text
fortran-docs://sources
fortran-docs://sources/{source_id}
fortran-docs://chunks/{chunk_id}
```

Run the reviewed retrieval benchmark against the local index with:

```bash
uv run fortran-mcp-benchmark --output benchmarks/results/sqlite-fts5.json
```

The report records ranking accuracy, negative-query accuracy, latency, and every individual query
result. It is a baseline for comparing future lexical, semantic, or hybrid search providers.

To build and evaluate the optional local semantic index:

```bash
uv sync --extra semantic
uv run fortran-mcp-semantic-index
uv run fortran-mcp-benchmark --provider semantic \
  --output benchmarks/results/semantic-bge-small-en-v1.5.json
uv run fortran-mcp-benchmark --provider hybrid \
  --output benchmarks/results/hybrid-bge-small-en-v1.5.json
```

The semantic-index command downloads the configured embedding model on its first run. The generated
vector index stays in the data directory and records both the model name and the lexical-index
checksum, so a stale or incompatible index is rejected.

Lexical search remains the server default. After building the semantic index, select another local
provider with `FORTRAN_MCP_SEARCH_PROVIDER=semantic` or
`FORTRAN_MCP_SEARCH_PROVIDER=hybrid`.

See [Connect an MCP client](docs/clients.md) for Codex, Claude Desktop, and generic stdio
configuration examples.

## Planned sources

- ISO Fortran standards and corrigenda
- Vendor compiler documentation and language extensions
- Build-system documentation for fpm, CMake, and Make
- Fortran Standard Library documentation
- C interoperability and OpenMP references
- Dialect, compatibility, modernization, and migration guides

Source licensing and redistribution terms will be recorded before documents enter the library.
The reviewed source inventory lives in [`docs/sources.toml`](docs/sources.toml); its policy is
described in [`docs/README.md`](docs/README.md).

## License

The server software is available under the [MIT License](LICENSE). Ingested documentation retains its
original copyright and license.
