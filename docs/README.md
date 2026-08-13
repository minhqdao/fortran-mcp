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
