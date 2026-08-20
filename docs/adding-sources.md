# Adding or updating a documentation source

Use this workflow for material shipped in the shared core. It is intentionally stricter than
indexing private notes: Fortran MCP redistributes transformed source text to other users.

## 1. Prove the gap

Write a few realistic questions that the current corpus cannot answer reliably. Prefer broadly
useful workflows over niche completeness. Record baseline ranks before adding content.

## 2. Review rights and scope

Verify the exact files and revision. Record the copyright/license, required notices, whether
transformation and redistribution are allowed, and why the material is authoritative or useful.
Do not infer permission from public access, repository code licensing, or educational intent.

Select the smallest coherent subset that answers the questions. Avoid duplicate editions,
boilerplate, implementation internals, generated API repetition, and near-copies of existing
sources.

## 3. Register the source

Add a pinned entry to `docs/sources.toml` and its complete required notice to
`docs/licenses/<source-id>.txt`. Use native text when practical. If conversion or selection is
necessary, add a deterministic converter, a modification notice where required, an expected output
count, and focused converter tests.

If a fetched document is generated navigation or other measured retrieval noise, list its exact
converted path in `excluded_document_paths`. Keep exclusions narrow and explain the evidence in the
registry notes; ingestion still preserves the document while chunk building omits it.

Inspect the result in human- or machine-readable form:

```bash
uv run fortran-mcp source list
uv run fortran-mcp source list --json
```

## 4. Materialize and measure

For a newly registered source:

```bash
uv run fortran-mcp source sync SOURCE_ID --data-dir data
uv run fortran-mcp-benchmark --output benchmarks/results/sqlite-fts5.json
uv run fortran-mcp-contributions --data-dir data \
  --output benchmarks/results/source-contributions.json
```

The sync command validates IDs before writing, downloads only a missing immutable ingestion,
rebuilds that source's chunks, and rebuilds the lexical index once. Use a fresh data directory for
a changed upstream revision or a clean release rebuild.

Add the gap questions to `benchmarks/retrieval.toml`. Compare unique passes, regressions, chunk and
compressed core cost, vector count, latency, and negative-query behavior. The contribution report
rebuilds the lexical corpus once per omitted source. `passes_lost_without_source` records all
ranking-dependent losses, `unique_passes` narrows those to cases whose matching baseline passage
came from that source, and `recovered_passes_without_source` reveals retrieval interference. Reject
or narrow a source when its weight or interference outweighs its benefit.

## 5. Finish the change

Update source counts and scope descriptions where relevant, then run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
git diff --check
```

Do not commit `data/`, `dist/`, or the local `todo.md`. Release bundles are built separately from a
clean, fully measured index.
