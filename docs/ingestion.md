# Ingestion and corpus notes

This document collects the maintainer-facing ingestion pipeline, build commands, and
per-source scope notes that used to live in the README. End users do not need any
of this: they install prebuilt data bundles.

## Data directory

Set `FORTRAN_MCP_DATA_DIR` to keep generated documents and indexes elsewhere, such as
the repository `data/` directory during maintainer work or a larger disk. All data
commands and the server use that location.

The command writes immutable source files and a checksum record below the configured
per-user data directory. It refuses to overwrite an existing ingestion.

## Registry and sync

Maintainers can inspect the reviewed registry and run the complete source-to-index
pipeline with:

```bash
uv run fortran-mcp source list
uv run fortran-mcp source sync SOURCE_ID --data-dir data
```

`source sync` validates every ID before writing, downloads only missing immutable
records, rebuilds their chunks, and rebuilds the lexical index once. For a changed
pinned revision or a release-wide rebuild, use a fresh data directory rather than
mutating old ingestion records.

See [Adding or updating a documentation source](adding-sources.md) for the
provenance, licensing, selection, and benchmark gate.

## Lower-level commands

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

The core collection also includes separately identifiable Fortran-lang references for
intrinsic procedures, the quickstart, best practices, object-oriented programming,
Fortran 95, building and linking, Python-to-Fortran translation, and floating-point
comparisons. They are pinned to one reviewed upstream revision and remain
independently filterable in search results.

Build citation-preserving document chunks after ingestion. These lower-level
commands are useful when working on a converter individually; `source sync`
already builds chunks and the lexical index:

```bash
uv run fortran-mcp-build fpm-0.13.0-docs
uv run fortran-mcp-build stdlib-0.8.1-docs
uv run fortran-mcp-build cmake-4.4.0-fortran-docs
uv run fortran-mcp-build openmp-6.0.1-fortran-examples
uv run fortran-mcp-build gnu-make-4.4.1-build-reference
uv run fortran-mcp-build numpy-2.5.2-f2py-docs
uv run fortran-mcp-build fypp-3.2-manual
uv run fortran-mcp-build openmpi-5.0.10-fortran-reference
uv run fortran-mcp-build fortitude-0.9.2-reference
uv run fortran-mcp-build codee-open-catalog-fortran-subset
uv run fortran-mcp-build old-fortran-programming-idioms
uv run fortran-mcp-build prima-modernization-case-study
uv run fortran-mcp-build beliavsky-fortran-packages-list
uv run fortran-mcp-build fortran-lang-package-index-additions
uv run fortran-mcp-index
```

## Per-source scope notes

The OpenMP source contains the official 6.0.1 explanatory examples that have
corresponding Fortran code. Its reviewed converter retains shared and
Fortran-specific explanations, embeds the fixed- and free-form source examples, and
excludes C/C++ listings. It is practical guidance rather than the normative OpenMP
specification.

The GNU Make source is a deliberately small set of official 4.4.1 manual sections
covering rules, prerequisites, automatic variables, parallel and recursive builds,
diagnostics, and the built-in Fortran compiler variables and rules. Its
modified-title and attribution notice, required cover texts, and complete GFDL are
retained.

The Fypp source is the complete compact official 3.2 manual. It adds the
preprocessor language, command-line definitions and includes, macro scopes, line
markers, and Fortran-specific folding pitfalls that are not covered by the existing
fpm configuration or F2PY generic-interface example. The pinned RST is converted
to citation-ready Markdown without changing its substantive content.

The Fortitude source adds practical diagnostics for correctness, modernization,
obsolete features, portability, and style. It uses Fortitude's pinned native
Markdown: one page per rule plus the small set of pages needed to install, run, and
configure the linter. Parser sources, tests, media, editor setup, integrations, and
release history are excluded. The material complements language and compiler
references; it is not treated as normative Fortran guidance.

The Codee Open Catalog source is limited to five independently useful pages that
fill measured gaps: loop-invariant conditionals, three initialization hazards, and
array-bounds errors. Its converter retains shared guidance and Fortran examples,
removes C/C++ examples, rewrites internal links to the pinned revision, and adds
the Apache-required modification notice. The rest of the catalog is excluded
because it substantially overlaps existing sources or did not justify its
retrieval weight. This is community guidance, not normative material or a product
endorsement.

The legacy-migration material has two complementary roles. _Old programming idioms
explained_ converts nine MIT-licensed chapters about the meaning, hazards, and
modern alternatives of old Fortran constructs. Its bibliography supplies external
citation links but is not itself indexed; the unfinished outline, separate
examples, PDF, and a redundant BLOCK DATA section that ranked below Fortitude's
guidance are excluded. The much smaller PRIMA case-study subset contributes an
official numerical-software workflow: establish a faithful reference, convert
layout first, and test after every tiny refactoring. Neither source is treated as a
language standard.

Ecosystem discovery uses two small, complementary directories. Beliavsky's actively
curated list is the primary source and retains all 396 categorized fpm-compatible
projects. The Fortran-lang package index adds 204 repositories absent from that
snapshot; its 68 normalized-URL overlaps are removed deterministically. These
entries help users find existing libraries and tools, but inclusion is not an
endorsement or a guarantee of maintenance, licensing, compatibility, or a current
successful build. Always check the linked project before adoption.

## GNU Fortran manual

The GNU Fortran manual is generated from its pinned Texinfo sources. Its converter
invokes GNU Texinfo, so maintainers need GNU Texinfo 7.3 and the optional
conversion dependency:

```bash
uv sync --extra ingest
```

On macOS, install Texinfo with `brew install texinfo` and add its `bin` directory to
`PATH` as instructed by Homebrew. Texinfo is build-time maintainer tooling; users
of prebuilt data bundles do not need it.

Once Texinfo is available, this source is materialized like any other, either through
the normal review workflow:

```bash
uv run fortran-mcp source sync gfortran-16.2.0-manual --data-dir data
```

or with the lower-level commands when iterating on the converter:

```bash
uv run fortran-mcp-ingest gfortran-16.2.0-manual
uv run fortran-mcp-build gfortran-16.2.0-manual
```

## Search and retrieval

The MCP server exposes `search_fortran_docs`, which returns ranked passages with
the source, version, authority, document type, topical facets, heading hierarchy,
line range, and published documentation URL. Searches can be narrowed by source ID,
document type, authority, topic, compiler, source version, or Fortran language
version. For example, clients can combine `compiler="gfortran"` and
`version="16.2.0"`. A Fortran language-version filter is intended for
edition-specific sources, rather than as a claim that a compiler completely
implements an edition. Applicability filters are resolved before ranking for
lexical, semantic, and hybrid retrieval.

It also exposes MCP resources for registered sources, source provenance, and exact
chunks:

```text
fortran-docs://sources
fortran-docs://sources/{source_id}
fortran-docs://chunks/{chunk_id}
```

Run the reviewed retrieval benchmark against the local index with:

```bash
uv run fortran-mcp-benchmark --output benchmarks/results/sqlite-fts5.json
```

The report records ranking accuracy, negative-query accuracy, latency, and every
individual query result. It is a baseline for comparing future lexical, semantic,
or hybrid search providers.

To measure whether each source earns its footprint, run the leave-one-source-out
analysis:

```bash
uv run fortran-mcp-contributions --data-dir data \
  --output benchmarks/results/source-contributions.json
```

It records unique passes, regressions, vector and byte costs, and latency for the
baseline and each omitted source. The concise reviewed result lives in
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

The semantic-index command downloads the configured embedding model on its first
run. Later builds reuse vectors whose model and embedded passage content are
unchanged, embed only new or changed chunks, and discard removed chunks. Pass
`--rebuild` to regenerate every vector. Chunks are embedded in length-sorted
batches, which roughly halves indexing time on mixed-length corpora without
changing any embedding. The generated index stays in the data directory and
records both the model name and the lexical-index checksum, so a stale or
incompatible index is rejected.

Lexical search remains the server default. After building the semantic index,
select another local provider with `FORTRAN_MCP_SEARCH_PROVIDER=semantic` or
`FORTRAN_MCP_SEARCH_PROVIDER=hybrid`.

Hybrid search conservatively returns no passages when its top semantic score is
below the reviewed baseline threshold. An explicit source filter bypasses this
automatic abstention because the caller has already stated which documentation
applies. An explicit registered dialect name, such as OpenMP, can also establish
applicability when lexical results from that dialect are present. The threshold
is calibrated against both supported questions and uncovered, domain-adjacent
questions, and must be reviewed whenever the core source collection or embedding
model changes.
```
