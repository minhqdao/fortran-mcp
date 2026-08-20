# Contributing

Fortran MCP welcomes focused fixes, retrieval improvements, and well-justified documentation
sources. The project optimizes for breadth and usefulness per byte, not corpus size.

## Start here

```bash
git clone https://github.com/minhqdao/fortran-mcp.git
cd fortran-mcp
uv sync --locked --all-extras --all-groups
uv run pytest
```

Before submitting a change, run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Behavior changes should include tests and concise documentation. Generated `data/` and `dist/`
artifacts are ignored and must not be committed.

## Documentation sources

Read [Adding or updating a source](docs/adding-sources.md) first. Every source needs demonstrated
retrieval value, exact pinned provenance, explicit redistribution rights, required notices, and a
measured benchmark result. A relevant or reputable source is not automatically suitable for the
core bundle.

Use `uv run fortran-mcp source list --json` for machine-readable registry inspection and
`uv run fortran-mcp source sync SOURCE_ID --data-dir data` to run the normal ingestion-to-index
pipeline for a newly approved entry.

## Scope and safety

Security-sensitive changes include downloads, archive handling, path validation, checksums,
catalogs, bundle installation, HTTP transport, and subprocess execution. Preserve size limits,
HTTPS requirements, atomic writes, and explicit trust boundaries. Avoid unrelated cleanup in the
same change.
