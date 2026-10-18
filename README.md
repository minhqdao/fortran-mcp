# Fortran MCP

[![CI](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fortran-mcp.svg)](https://pypi.org/project/fortran-mcp/)
[![MCP](https://img.shields.io/badge/MCP-2.0-2F4F8G?labelColor=1a1a2e&color=0f4c81)](https://spec.modelcontextprotocol.io/)
[![RAG](https://img.shields.io/badge/RAG-cited%20retrieval-0e7c7b)](https://github.com/minhqdao/fortran-mcp)
[![Search](https://img.shields.io/badge/search-lexical%20+%20semantic%20+%20hybrid-0f4c81)](https://github.com/minhqdao/fortran-mcp/blob/main/benchmarks/results/)
[![Sources](https://img.shields.io/badge/sources-23-c88603?logo=gitbook&logoColor=white)](https://github.com/minhqdao/fortran-mcp/blob/main/docs/sources.toml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/minhqdao/fortran-mcp/blob/main/LICENSE)

Use Fortran MCP to improve AI-assisted Fortran development with cited documentation on language features, compiler behavior, build systems, and the wider ecosystem.

It supports lexical, semantic, and hybrid search, returning relevant passages with source attribution, version information, and links to the original documentation.

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

Install the Fortran MCP server:

```bash
uv tool install fortran-mcp
```

Semantic and hybrid search require additional dependencies:

```bash
uv tool install "fortran-mcp[semantic]"
```

Data bundles are installed automatically on first run. You can also install them beforehand to avoid an initial delay:

```bash
fortran-mcp data install core      # for lexical search
fortran-mcp data install semantic  # for semantic and hybrid search
```

Check the installation:

```bash
fortran-mcp doctor
```

Use `FORTRAN_MCP_AUTO_INSTALL=0` to disable automatic installation, or set `FORTRAN_MCP_CATALOG` to point to a local catalog path or HTTPS URL.

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

## Ingestion

Maintainers can inspect the reviewed registry and run the complete source-to-index pipeline with:

```bash
uv run fortran-mcp source list
uv run fortran-mcp source sync SOURCE_ID --data-dir data
```

See
[Adding or updating a documentation source](https://github.com/minhqdao/fortran-mcp/blob/main/docs/adding-sources.md)
for the provenance, licensing, selection, and benchmark gate. The lower-level commands below
remain useful when working on converters individually.

Fetch an approved documentation source by its registry ID:

```bash
uv run fortran-mcp-ingest fpm-0.13.0-docs
uv run fortran-mcp-ingest stdlib-0.8.1-docs
uv run fortran-mcp-ingest cmake-4.4.0-fortran-docs
uv run fortran-mcp-ingest openmp-6.0.1-fortran-examples
uv run fortran-mcp-ingest gnu-make-4.4.1-build-reference
uv run fortran-mcp-ingest numpy-2.5.2-f2py-docs
uv run fortran-mcp-ingest fypp-3.2-manual
uv run fortran-mcp-ingest openmpi-5.0.10-fortran-reference
uv run fortran-mcp-ingest fortitude-0.9.2-reference
uv run fortran-mcp-ingest codee-open-catalog-fortran-subset
uv run fortran-mcp-ingest old-fortran-programming-idioms
uv run fortran-mcp-ingest prima-modernization-case-study
uv run fortran-mcp-ingest beliavsky-fortran-packages-list
uv run fortran-mcp-ingest fortran-lang-package-index-additions
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

The Fypp source is the complete compact official 3.2 manual. It adds the preprocessor language,
command-line definitions and includes, macro scopes, line markers, and Fortran-specific folding
pitfalls that are not covered by the existing fpm configuration or F2PY generic-interface example.
The pinned RST is converted to citation-ready Markdown without changing its substantive content.

The Fortitude source adds practical diagnostics for correctness, modernization, obsolete features,
portability, and style. It uses Fortitude's pinned native Markdown: one page per rule plus the small
set of pages needed to install, run, and configure the linter. Parser sources, tests, media, editor
setup, integrations, and release history are excluded. The material complements language and
compiler references; it is not treated as normative Fortran guidance.

The Codee Open Catalog source is limited to five independently useful pages that fill measured
gaps: loop-invariant conditionals, three initialization hazards, and array-bounds errors. Its
converter retains shared guidance and Fortran examples, removes C/C++ examples, rewrites internal
links to the pinned revision, and adds the Apache-required modification notice. The rest of the
catalog is excluded because it substantially overlaps existing sources or did not justify its
retrieval weight. This is community guidance, not normative material or a product endorsement.

The legacy-migration material has two complementary roles. _Old programming idioms explained_
converts nine MIT-licensed chapters about the meaning, hazards, and modern alternatives of old
Fortran constructs. Its bibliography supplies external citation links but is not itself indexed;
the unfinished outline, separate examples, PDF, and a redundant BLOCK DATA section that ranked
below Fortitude's guidance are excluded.
The much smaller PRIMA case-study subset contributes an official numerical-software workflow:
establish a faithful reference, convert layout first, and test after every tiny refactoring. Neither
source is treated as a language standard.

Ecosystem discovery uses two small, complementary directories. Beliavsky's actively curated list is
the primary source and retains all 396 categorized fpm-compatible projects. The Fortran-lang package
index adds 204 repositories absent from that snapshot; its 68 normalized-URL overlaps are removed
deterministically. These entries help users find existing libraries and tools, but inclusion is not
an endorsement or a guarantee of maintenance, licensing, compatibility, or a current successful
build. Always check the linked project before adoption.

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
uv run fortran-mcp-build fortitude-0.9.2-reference
uv run fortran-mcp-build codee-open-catalog-fortran-subset
uv run fortran-mcp-build old-fortran-programming-idioms
uv run fortran-mcp-build prima-modernization-case-study
uv run fortran-mcp-build beliavsky-fortran-packages-list
uv run fortran-mcp-build fortran-lang-package-index-additions
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

To measure whether each source earns its footprint, run the leave-one-source-out analysis:

```bash
uv run fortran-mcp-contributions --data-dir data \
  --output benchmarks/results/source-contributions.json
```

It records unique passes, regressions, vector and byte costs, and latency for the baseline and each
omitted source. The concise reviewed result lives in
`benchmarks/results/source-contributions.md`.

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
chunks, and discard removed chunks. Pass `--rebuild` to regenerate every vector. Chunks are embedded
in length-sorted batches, which roughly halves indexing time on mixed-length corpora without
changing any embedding. The generated index stays in the data directory and records both the model
name and the lexical-index checksum, so a stale or incompatible index is rejected.

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
  --output dist/fortran-mcp-core.zip --data-version 2026.08.1
FORTRAN_MCP_DATA_DIR=data uv run fortran-mcp-bundle build semantic \
  --output dist/fortran-mcp-semantic.zip --data-version 2026.08.1
uv run fortran-mcp-bundle verify dist/fortran-mcp-core.zip
uv run fortran-mcp data install core --bundle dist/fortran-mcp-core.zip
uv run fortran-mcp-catalog build --data-version 2026.08.1 \
  --output dist/catalog.json \
  dist/fortran-mcp-core.zip dist/fortran-mcp-semantic.zip
uv run fortran-mcp-catalog install core --catalog dist/catalog.json
```

### Publishing a data release

1. Rebuild both bundles deterministically from a current data directory and regenerate the catalog
   (commands above). Pick a new `YYYY.MM.N` `data_version` for each data release and use it for
   both bundles and the catalog.
2. Verify every artifact on its own and through the catalog:
   ```bash
   uv run fortran-mcp-bundle verify dist/fortran-mcp-core.zip
   uv run fortran-mcp-bundle verify dist/fortran-mcp-semantic.zip
   uv run fortran-mcp-catalog verify dist/catalog.json
   ```
3. Smoke-test the exact artifacts before upload:
   ```bash
   rm -rf /tmp/release-check
   FORTRAN_MCP_DATA_DIR=/tmp/release-check uv run fortran-mcp data install core \
     --catalog dist/catalog.json
   FORTRAN_MCP_DATA_DIR=/tmp/release-check uv run fortran-mcp data install semantic \
     --catalog dist/catalog.json
   FORTRAN_MCP_DATA_DIR=/tmp/release-check uv run fortran-mcp data verify
   ```
4. Upload all assets together to a draft release so the catalog never points at missing files:
   ```bash
   gh release create v<version> --draft --title "Fortran MCP <version> data release" \
     dist/catalog.json dist/fortran-mcp-core.zip dist/fortran-mcp-semantic.zip
   ```
5. Inspect the draft (`gh release view v<version>`): exactly three assets, correct sizes, no stray
   uploads. Publishing is the activation step because `releases/latest/download/catalog.json`
   resolves to this release immediately.
6. Publish only after every asset is present:
   ```bash
   gh release edit v<version> --draft=false
   ```
7. Post-publish, exercise the real user path without `--catalog`:
   `fortran-mcp data install core && fortran-mcp data verify`. Release assets are only downloadable
   anonymously from a public repository, so this final check requires the repository to be public.

There is no automated rollback: fix the artifacts and cut a new data release instead. Old installs
remain valid because verification is checksum-pinned.

Normal users use the built-in GitHub Release catalog through the unified command:

```bash
fortran-mcp data install core
fortran-mcp data verify
fortran-mcp data remove core
```

Running `fortran-mcp` without a subcommand still starts the stdio MCP server, so existing client
configuration remains compatible. `fortran-mcp doctor` lists installed data, including custom
corpora built with `source sync`; `fortran-mcp doctor --json` is machine-readable. `data remove`
removes exactly one named data package, keeps unrelated files in the data
directory, and removes documentation data only — not the Python package itself. If installed with
`uv tool`, uninstall that separately with `uv tool uninstall fortran-mcp`.

Bundles use a versioned manifest, deterministic ZIP metadata, stable file ordering, and SHA-256
checksums for every payload. The default catalog is loaded over HTTPS from the latest GitHub Release;
`--catalog` accepts another HTTPS URL or local path. Relative artifact paths are resolved against the
catalog URL, and the advertised archive size and SHA-256 are checked before the bundle's own
manifest and payload checks. Installation enforces server compatibility and installs semantic data
only alongside the exact required core index. See
[Data bundle format](https://github.com/minhqdao/fortran-mcp/blob/main/docs/bundles.md) for the
artifact contract.

See [Contributing](https://github.com/minhqdao/fortran-mcp/blob/main/CONTRIBUTING.md) for local
checks and source-submission expectations. Coding agents should also read
[AGENTS.md](https://github.com/minhqdao/fortran-mcp/blob/main/AGENTS.md) for the repository map and
invariants.

## Source policy

The 23-source core is intentionally frozen for the first release. A new source is considered only
when realistic benchmark questions demonstrate a gap, the exact material has clear transformation
and redistribution rights, and a trial shows enough unique retrieval value to justify its bytes and
ranking interference. Public access alone is not permission to redistribute documentation; this is
especially relevant to standards, books, and vendor manuals.

The reviewed source inventory lives in
[`docs/sources.toml`](https://github.com/minhqdao/fortran-mcp/blob/main/docs/sources.toml); its policy
is described in
[`docs/README.md`](https://github.com/minhqdao/fortran-mcp/blob/main/docs/README.md).

## License

The server software is available under the
[MIT License](LICENSE). [Sources](docs/sources.toml) retain their
original copyrights and [licenses](docs/licenses/).
