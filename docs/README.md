# Fortran documentation

`sources.toml` is the reviewed inventory of Fortran documentation sources. Registering a source
does not automatically authorize downloading, storing, or redistributing its content.

Each entry records provenance, scope, revision, and licensing status. Only sources marked
`redistributable` may be copied into a distributable collection. Sources marked `link-only` may be
indexed only when that use is allowed, and `review-required` sources must not be ingested.

Checksums and retrieval timestamps belong to downloaded document records, which will be added
with the ingestion pipeline.

Run an approved ingestion with `uv run fortran-mcp-ingest SOURCE_ID`. Downloaded files and their
provenance record are written below the configured data directory. Maintainers may set
`FORTRAN_MCP_DATA_DIR=data` to use the repository-local directory, which is excluded from version
control.

Some upstream formats require a reviewed conversion before chunking. Such sources declare their
converter and entrypoint in the registry, record the converter version in their ingestion record,
and may declare an expected document count. The GNU Fortran manual requires GNU Texinfo 7.3 and
the `ingest` optional dependency; these are maintainer requirements and are not needed to query a
prebuilt bundle. The built-in OpenMP Examples converter selects documents with official Fortran
examples, removes C/C++-specific sections, and embeds the corresponding fixed- or free-form source
code alongside its explanation.
The GNU Make converter generates only the reviewed sections that close measured Fortran build
coverage gaps and records a modified title, all principal authors, the selection notice, cover
texts, and complete GFDL material.
The Fypp converter turns the complete compact official 3.2 RST manual into citation-ready Markdown.
It retains the preprocessor language, command-line usage, Fortran-specific line-folding cautions,
examples, build integration, and API overview because the complete manual has high utility at
negligible corpus weight.
Fortitude needs no converter: the pinned release already contains one native Markdown document per
rule. Its source entry deliberately adds only those rule pages and the minimum operational reference.
The Codee converter enforces a five-page allowlist, removes C/C++ example sections, rewrites links
to the pinned revision, and places a prominent modification notice in every generated page. The
selection is intentionally community-level, non-normative guidance rather than the full catalog.
The old-idioms converter turns nine selected LaTeX chapters into citation-preserving Markdown-like
text, preserves external links from its bibliography, and excludes the unfinished outline,
separate examples, PDF, and overlapping BLOCK DATA section. The PRIMA
converter retains only the official README passages that explain the modernization goal and its
incremental differential-testing method. Both generated sources carry modification notices.
