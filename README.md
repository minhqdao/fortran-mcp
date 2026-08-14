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
server uses the standard input/output transport by default. For local HTTP testing, run:

```bash
uv run fortran-mcp --transport streamable-http
```

The Streamable HTTP endpoint is then available at `http://127.0.0.1:1957/mcp`. Stdio remains the
recommended local-client transport. HTTP hosting, TLS, authentication, and proxy configuration are
deployment concerns and are intentionally not prescribed by this project yet. Run quality checks
with:

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
uv run fortran-mcp-ingest cmake-4.4.0-fortran-docs
uv run fortran-mcp-ingest openmp-6.0.1-fortran-examples
uv run fortran-mcp-ingest gnu-make-4.4.1-build-reference
uv run fortran-mcp-ingest numpy-2.5.2-f2py-docs
```

The core collection also includes separately identifiable Fortran-lang references for intrinsic
procedures, the quickstart, best practices, object-oriented programming, Fortran 95, building and
linking, Python-to-Fortran translation, and floating-point comparisons. They are pinned to one
reviewed upstream revision and remain independently filterable in search results.

The OpenMP source contains the official 6.0.1 explanatory examples that have corresponding
Fortran code. Its reviewed converter retains shared and Fortran-specific explanations, embeds the
fixed- and free-form source examples, and excludes C/C++ listings. It is practical guidance rather
than the normative OpenMP specification.

The GNU Make source is a deliberately small set of official 4.4.1 manual sections covering rules,
prerequisites, automatic variables, parallel and recursive builds, diagnostics, and the built-in
Fortran compiler variables and rules. Its modified-title and attribution notice, required cover
texts, and complete GFDL are retained.

The GNU Fortran manual is generated from its pinned Texinfo sources. Maintainers building that
source need GNU Texinfo 7.3 and the optional conversion dependency:

```bash
uv sync --extra ingest
uv run fortran-mcp-ingest gfortran-16.2.0-manual
uv run fortran-mcp-build gfortran-16.2.0-manual
```

On macOS, install Texinfo with `brew install texinfo` and add its `bin` directory to `PATH` as
instructed by Homebrew. Texinfo is build-time maintainer tooling; users of prebuilt data bundles do
not need it.

The command writes immutable source files and a checksum record below the configured per-user data
directory. It refuses to overwrite an existing ingestion.

Set `FORTRAN_MCP_DATA_DIR` to keep generated documents and indexes elsewhere, such as the repository
`data/` directory during maintainer work or a larger disk. All data commands and the server use that
location.

Build citation-preserving document chunks after ingestion:

```bash
uv run fortran-mcp-build fpm-0.13.0-docs
uv run fortran-mcp-build stdlib-0.8.1-docs
uv run fortran-mcp-build cmake-4.4.0-fortran-docs
uv run fortran-mcp-build openmp-6.0.1-fortran-examples
uv run fortran-mcp-build gnu-make-4.4.1-build-reference
uv run fortran-mcp-index
```

The MCP server exposes `search_fortran_docs`, which returns ranked passages with the source,
version, authority, document type, topical facets, heading hierarchy, line range, and published
documentation URL. Searches can be narrowed by source ID, document type, authority, topic,
compiler, source version, or Fortran language version. For example, clients can combine
`compiler="gfortran"` and `version="16.2.0"`. A Fortran language-version filter is intended for
edition-specific sources, rather than as a claim that a compiler completely implements an edition.
Applicability filters are resolved before ranking for lexical, semantic, and hybrid retrieval.

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

The semantic-index command downloads the configured embedding model on its first run. Later builds
reuse vectors whose model and embedded passage content are unchanged, embed only new or changed
chunks, and discard removed chunks. Pass `--rebuild` to regenerate every vector. The generated index
stays in the data directory and records both the model name and the lexical-index checksum, so a
stale or incompatible index is rejected.

Lexical search remains the server default. After building the semantic index, select another local
provider with `FORTRAN_MCP_SEARCH_PROVIDER=semantic` or
`FORTRAN_MCP_SEARCH_PROVIDER=hybrid`.

Hybrid search conservatively returns no passages when its top semantic score is below the reviewed
baseline threshold. An explicit source filter bypasses this automatic abstention because the caller
has already stated which documentation applies. An explicit registered dialect name, such as
OpenMP, can also establish applicability when lexical results from that dialect are present. The
threshold is calibrated against both supported
questions and uncovered, domain-adjacent questions, and must be reviewed whenever the core source
collection or embedding model changes.

## Data bundles

Normal users will consume prebuilt data bundles rather than run ingestion or indexing locally. The
current tooling defines two roles: `core` contains the lexical index and required source license
notices; `semantic` contains document vectors and declares the exact core-index checksum and query
model it requires.

Build and verify local artifacts with:

```bash
FORTRAN_MCP_DATA_DIR=data uv run fortran-mcp-bundle build core \
  --output dist/fortran-mcp-core.zip
FORTRAN_MCP_DATA_DIR=data uv run fortran-mcp-bundle build semantic \
  --output dist/fortran-mcp-semantic.zip
uv run fortran-mcp-bundle verify dist/fortran-mcp-core.zip
uv run fortran-mcp-bundle install dist/fortran-mcp-core.zip
uv run fortran-mcp-catalog build --data-version 2026.08.1 \
  --output dist/catalog.json \
  dist/fortran-mcp-core.zip dist/fortran-mcp-semantic.zip
uv run fortran-mcp-catalog install core --catalog dist/catalog.json
```

Normal users use the unified command instead:

```bash
fortran-mcp data install core --catalog dist/catalog.json
fortran-mcp data status
fortran-mcp data verify
fortran-mcp data remove
```

Running `fortran-mcp` without a subcommand still starts the stdio MCP server, so existing client
configuration remains compatible. `data status --json` provides a machine-readable readiness report.
`data remove` asks for confirmation, then removes installed bundle files while preserving unrelated
files in the data directory; pass `--yes` for non-interactive use. It removes documentation data,
not the Python package itself. If installed with `uv tool`, uninstall that separately with
`uv tool uninstall fortran-mcp`.

Bundles use a versioned manifest, deterministic ZIP metadata, stable file ordering, and SHA-256
checksums for every payload. Installation accepts a local path or explicit HTTPS URL, verifies the
complete archive before writing it, enforces server compatibility, and installs semantic data only
alongside the exact required core index. Automatic release discovery and publishing are intentionally
not implemented yet. A local catalog provides independent data versioning, whole-archive checksums,
download sizes, and role-based installation without assuming a future release URL. See
[Data bundle format](docs/bundles.md) for the artifact contract.

See [Connect an MCP client](docs/clients.md) for Codex, Claude Desktop, and generic stdio
configuration examples.

## Planned sources

- ISO Fortran standards and corrigenda
- Vendor compiler documentation and language extensions
- Additional build-system documentation beyond the included fpm, CMake, Fortran-lang, and GNU Make material
- Fortran Standard Library documentation
- C interoperability and the normative OpenMP specification
- Dialect, compatibility, modernization, and migration guides

Source licensing and redistribution terms will be recorded before documents enter the library.
The reviewed source inventory lives in [`docs/sources.toml`](docs/sources.toml); its policy is
described in [`docs/README.md`](docs/README.md).

## License

The server software is available under the [MIT License](LICENSE). Ingested documentation retains its
original copyright and license.
