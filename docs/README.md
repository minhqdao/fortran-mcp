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
prebuilt bundle.
