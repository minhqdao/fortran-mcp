# Working on Fortran MCP

## Product objective

Maximize useful, cited Fortran coverage per byte. Favor broad, pragmatic material and simple local
machinery over exhaustive corpora, speculative abstractions, or mandatory hosted services. Lexical
search is the lean default; semantic and hybrid retrieval are optional.

## Repository map

- `src/fortran_mcp/`: server, retrieval, ingestion, bundles, catalog, and CLI code.
- `docs/sources.toml`: reviewed source registry and provenance source of truth.
- `docs/licenses/`: notices that must accompany core-bundle sources.
- `benchmarks/retrieval.toml`: reviewed retrieval expectations.
- `benchmarks/results/`: checked-in reports for the current corpus.
- `tests/`: unit, safety, packaging, retrieval, and stdio integration tests.
- `data/` and `dist/`: ignored generated artifacts; never treat them as source of truth.
- `todo.md`: local-only working memory when present; it is intentionally excluded from Git.

## Non-negotiable invariants

1. Do not ingest content until the exact files, revision, license, notices, and redistribution policy
   are recorded. Website visibility is not redistribution permission.
2. Approved sources must be pinned and reproducible. Keep generated passages attributable and
   independently filterable; do not silently merge provenance.
3. Add content only for a demonstrated retrieval gap. Measure focused questions, added chunks and
   bytes, regressions, and overlap before accepting it.
4. Preserve immutable ingestion, checksum verification, safe archive paths, download limits,
   deterministic bundles, and install-through-temporary-file behavior.
5. Keep normal installation small. Do not make converters, compilers, linters, or embedding models
   runtime dependencies of the lexical server.

## Common workflows

```bash
uv sync --locked --all-extras --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Inspect the registered corpus and materialize newly approved sources:

```bash
uv run fortran-mcp source list
uv run fortran-mcp source list --json
uv run fortran-mcp source sync SOURCE_ID --data-dir data
```

`source sync` validates every ID before writing, downloads only missing immutable records, rebuilds
their chunks, and rebuilds the lexical index once. For a changed pinned revision or a release-wide
rebuild, use a fresh data directory rather than mutating old ingestion records.

See `docs/adding-sources.md` before changing the corpus and `docs/bundles.md` before changing data
distribution. Run `fortran-mcp doctor` when debugging a user installation.

After changing chunking or corpus scope, regenerate the three retrieval reports and run
`uv run fortran-mcp-contributions --data-dir data --output <report.json>`. Use the reviewed summary
in `benchmarks/results/source-contributions.md` to judge whether each source earns its bytes; do not
infer contribution from source size alone.

## Change discipline

- Preserve unrelated work in a dirty tree and never commit ignored generated data.
- Update tests and concise user documentation with behavior changes.
- Keep errors actionable: say what failed, where, and the next safe command.
- Prefer an existing dependency or a small standard-library implementation over adding runtime
  weight.
- Do not mark release checks complete based on stale `dist/` artifacts.
